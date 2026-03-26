import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from chunk import chunk_document
from db import get_connection, release_connection
from embed import embed_and_store_chunks
from extract import run_extraction
from parse.email import parse_email
from parse.excel import parse_excel
from parse.pdf import parse_pdf


_FILE_HASH_COLUMN_READY = False
FILE_INGEST_TIMEOUT_SECONDS = 240
PARSE_TIMEOUT_BY_TYPE_SECONDS = {
	"pdf": 90,
	"excel": 60,
	"email": 20,
}
EMBED_EXTRACT_TIMEOUT_SECONDS = 180


def detect_file_type(file_path: str) -> str:
	"""Detect file type by extension only."""
	suffix = Path(file_path).suffix.lower()
	if suffix == ".pdf":
		return "pdf"
	if suffix in {".xlsx", ".xls", ".csv"}:
		return "excel"
	if suffix in {".txt", ".eml"}:
		return "email"
	return "unknown"


def _compute_file_hash(file_path: str) -> str:
	"""Compute SHA-256 hash from file bytes."""
	hasher = hashlib.sha256()
	with open(file_path, "rb") as file:
		for chunk in iter(lambda: file.read(8192), b""):
			hasher.update(chunk)
	return hasher.hexdigest()


def _ensure_file_hash_column() -> None:
	"""Ensure documents.file_hash exists for duplicate detection."""
	global _FILE_HASH_COLUMN_READY
	if _FILE_HASH_COLUMN_READY:
		return

	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash TEXT")
			cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash)")
		conn.commit()
		_FILE_HASH_COLUMN_READY = True
	finally:
		release_connection(conn)


def check_duplicate(file_path: str) -> str | None:
	"""Return existing document id for duplicate file hash, otherwise None."""
	_ensure_file_hash_column()
	file_hash = _compute_file_hash(file_path)

	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT id::text FROM documents WHERE file_hash = %s LIMIT 1",
				(file_hash,),
			)
			row = cur.fetchone()
		return row[0] if row else None
	finally:
		release_connection(conn)


def _insert_document(
	document_id: str,
	filename: str,
	file_type: str,
	source_path: str,
	status: str,
	file_hash: str,
) -> None:
	"""Insert a document record using executemany."""
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.executemany(
				"""
				INSERT INTO documents (id, filename, file_type, source_path, status, file_hash)
				VALUES (%s::uuid, %s, %s, %s, %s, %s)
				""",
				[(document_id, filename, file_type, source_path, status, file_hash)],
			)
		conn.commit()
	finally:
		release_connection(conn)


def _update_document_status(
	document_id: str,
	status: str,
	error: str | None = None,
	word_count: int | None = None,
) -> None:
	"""Update document status and optional fields."""
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"""
				UPDATE documents
				SET status = %s,
					error = %s,
					word_count = COALESCE(%s, word_count)
				WHERE id = %s::uuid
				""",
				(status, error, word_count, document_id),
			)
		conn.commit()
	finally:
		release_connection(conn)


def _bulk_insert_chunks(document_id: str, chunks: list[dict]) -> None:
	"""Insert chunks with a single executemany call."""
	if not chunks:
		return

	rows = [
		(
			chunk["id"],
			document_id,
			chunk.get("content", ""),
			chunk.get("chunk_index"),
			chunk.get("chunk_type"),
			chunk.get("token_estimate"),
			json.dumps(chunk.get("metadata", {})),
		)
		for chunk in chunks
	]

	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.executemany(
				"""
				INSERT INTO chunks (id, document_id, content, chunk_index, chunk_type, token_estimate, metadata)
				VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb)
				""",
				rows,
			)
		conn.commit()
	finally:
		release_connection(conn)


def _bulk_insert_fields(document_id: str, fields: list[dict]) -> int:
	"""Insert extracted fields with a single executemany call."""
	if not fields:
		return 0

	rows = []
	for field in fields:
		field_name = field.get("field_name")
		if not field_name:
			continue
		confidence = str(field.get("confidence", "low")).lower()
		if confidence not in {"high", "medium", "low"}:
			confidence = "low"
		rows.append(
			(
				document_id,
				str(field.get("chunk_id")),
				str(field_name),
				str(field.get("field_value", "")),
				confidence,
			)
		)

	if not rows:
		return 0

	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.executemany(
				"""
				INSERT INTO extracted_fields (document_id, chunk_id, field_name, field_value, confidence)
				VALUES (%s::uuid, %s::uuid, %s, %s, %s)
				""",
				rows,
			)
		conn.commit()
		return len(rows)
	finally:
		release_connection(conn)


async def ingest_file(file_path: str) -> dict:
	"""Ingest a single file through parse, chunk, embed, extract, and persist steps."""
	filename = Path(file_path).name
	existing_document_id = check_duplicate(file_path)
	if existing_document_id:
		return {
			"document_id": existing_document_id,
			"filename": filename,
			"status": "already_ingested",
			"skipped": True,
			"already_ingested": True,
		}

	file_hash = _compute_file_hash(file_path)
	file_type = detect_file_type(file_path)

	if file_type == "unknown":
		skipped_document_id = str(uuid4())
		_insert_document(
			document_id=skipped_document_id,
			filename=filename,
			file_type=file_type,
			source_path=file_path,
			status="skipped",
			file_hash=file_hash,
		)
		return {
			"document_id": skipped_document_id,
			"filename": filename,
			"file_type": file_type,
			"status": "skipped",
			"skipped": True,
		}

	document_id = str(uuid4())
	_insert_document(
		document_id=document_id,
		filename=filename,
		file_type=file_type,
		source_path=file_path,
		status="pending",
		file_hash=file_hash,
	)

	try:
		parse_timeout = PARSE_TIMEOUT_BY_TYPE_SECONDS.get(file_type, 60)
		if file_type == "pdf":
			parsed = await asyncio.wait_for(asyncio.to_thread(parse_pdf, file_path), timeout=parse_timeout)
			parse_error = parsed.get("error")
		elif file_type == "excel":
			parsed = await asyncio.wait_for(asyncio.to_thread(parse_excel, file_path), timeout=parse_timeout)
			parse_error = parsed[0].get("error") if parsed and isinstance(parsed[0], dict) else None
		else:
			parsed = await asyncio.wait_for(asyncio.to_thread(parse_email, file_path), timeout=parse_timeout)
			parse_error = parsed.get("error")

		if parse_error:
			_update_document_status(document_id, status="failed", error=str(parse_error))
			return {
				"document_id": document_id,
				"filename": filename,
				"file_type": file_type,
				"status": "failed",
				"error": str(parse_error),
			}

		chunks = chunk_document(parsed, file_type)
		for chunk in chunks:
			chunk["id"] = str(uuid4())

		_update_document_status(document_id, status="processing")

		_, extracted_fields = await asyncio.wait_for(
			asyncio.gather(
				embed_and_store_chunks(document_id, chunks, file_type),
				run_extraction(document_id, chunks, file_type),
			),
			timeout=EMBED_EXTRACT_TIMEOUT_SECONDS,
		)

		_bulk_insert_chunks(document_id, chunks)
		field_count = _bulk_insert_fields(document_id, extracted_fields)

		word_count = sum(len(str(chunk.get("content", "")).split()) for chunk in chunks)
		_update_document_status(document_id, status="done", error=None, word_count=word_count)

		return {
			"document_id": document_id,
			"filename": filename,
			"file_type": file_type,
			"chunk_count": len(chunks),
			"field_count": field_count,
			"status": "done",
		}
	except asyncio.TimeoutError:
		error_message = "ingest timeout for %s after %ss" % (filename, FILE_INGEST_TIMEOUT_SECONDS)
		_update_document_status(document_id, status="failed", error=error_message)
		return {
			"document_id": document_id,
			"filename": filename,
			"file_type": file_type,
			"status": "failed",
			"error": error_message,
		}
	except asyncio.CancelledError:
		error_message = "ingest cancelled for %s" % filename
		_update_document_status(document_id, status="failed", error=error_message)
		raise
	except Exception as error:
		_update_document_status(document_id, status="failed", error=str(error))
		raise


async def ingest_file_with_timeout(file_path: str, timeout_seconds: int = FILE_INGEST_TIMEOUT_SECONDS) -> dict:
	"""Run ingest_file with a hard timeout so one stuck file cannot block batches."""
	filename = Path(file_path).name
	try:
		return await asyncio.wait_for(ingest_file(file_path), timeout=timeout_seconds)
	except asyncio.TimeoutError:
		return {
			"filename": filename,
			"file_type": detect_file_type(file_path),
			"chunk_count": 0,
			"field_count": 0,
			"status": "failed",
			"error": "timeout after %ss" % timeout_seconds,
		}


async def ingest_folder(folder_path: str) -> list[dict]:
	"""Ingest all files in a folder sequentially and continue on individual errors."""
	results: list[dict] = []
	folder = Path(folder_path)

	for path in sorted(folder.iterdir()):
		if not path.is_file():
			continue
		try:
			result = await ingest_file_with_timeout(str(path), timeout_seconds=FILE_INGEST_TIMEOUT_SECONDS)
			results.append(result)
		except Exception as error:
			print("Failed to ingest %s: %s" % (path.name, error))
			results.append(
				{
					"filename": path.name,
					"status": "failed",
					"error": str(error),
				}
			)
	return results
