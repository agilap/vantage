import asyncio
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from chunk import chunk_document
from db import get_connection, release_connection
from embed import embed_and_store_chunks
from extract import run_extraction
from parse.email import parse_email
from parse.excel import parse_excel
from parse.htm import parse_htm
from parse.pdf import parse_pdf


_FILE_HASH_COLUMN_READY = False
_FILE_TYPE_CONSTRAINT_READY = False
FILE_INGEST_TIMEOUT_SECONDS = 240
PARSE_TIMEOUT_BY_TYPE_SECONDS = {
	"pdf": 90,
	"excel": 60,
	"email": 20,
}
EMBED_EXTRACT_TIMEOUT_SECONDS = 900


def _file_size_mb(file_path: str) -> float:
	"""Return file size in MB, defaulting safely on file errors."""
	try:
		return Path(file_path).stat().st_size / (1024 * 1024)
	except Exception:
		return 0.0


def _ingest_timeout_for_file(file_path: str, file_type: str) -> int:
	"""Compute adaptive timeout so larger files get enough processing budget."""
	size_mb = _file_size_mb(file_path)
	if file_type == "pdf":
		# 90-page PDF at ~150 chunks: parsing ~30s + embedding ~20s +
		# batched extraction (6 batches * 25 chunks * ~3s avg + 2s sleep) ~120s
		# Total realistic ceiling: ~300s. Add 2x safety margin for retries.
		return int(min(1800, max(600, 300 + (size_mb * 40))))
	if file_type == "htm":
		return int(min(1200, max(300, 240 + (size_mb * 25))))
	if file_type == "excel":
		return int(min(900, max(240, 180 + (size_mb * 20))))
	if file_type == "email":
		return int(min(300, max(120, 90 + (size_mb * 10))))
	return FILE_INGEST_TIMEOUT_SECONDS


def _parse_timeout_for_file(file_path: str, file_type: str) -> int:
	"""Compute parse timeout with extra headroom for large files."""
	base = PARSE_TIMEOUT_BY_TYPE_SECONDS.get(file_type, 60)
	size_mb = _file_size_mb(file_path)
	if file_type == "pdf":
		return int(min(600, max(120, 90 + (size_mb * 15))))
	if file_type == "htm":
		return int(min(300, max(60, 45 + (size_mb * 10))))
	if file_type == "excel":
		return int(min(600, max(base, 60 + (size_mb * 12))))
	return int(base)


def _sniff_txt_type(file_path: str) -> str:
	"""Sniff a .txt file to determine if it is tabular or email-like."""
	try:
		with open(file_path, "r", encoding="utf-8", errors="replace") as file:
			lines = []
			for line in file:
				stripped = line.strip()
				if stripped:
					lines.append(stripped)
				if len(lines) >= 5:
					break

		if not lines:
			return "email"

		tab_lines = sum(1 for line in lines if "\t" in line)
		if tab_lines >= max(2, len(lines) // 2):
			return "excel"

		first = lines[0].lower()
		if any(first.startswith(header) for header in ("subject:", "from:", "to:", "date:", "message-id:")):
			return "email"

		if lines[0].count(",") >= 2:
			col_counts = [line.count(",") for line in lines]
			if max(col_counts) - min(col_counts) <= 1:
				return "excel"

		return "email"
	except Exception:
		return "email"


def detect_file_type(file_path: str) -> str:
	"""Detect file type by extension only."""
	suffix = Path(file_path).suffix.lower()
	if suffix == ".pdf":
		return "pdf"
	if suffix in {".xlsx", ".xls", ".xlsm", ".xlsb", ".ods"}:
		return "excel"
	if suffix in {".csv", ".tsv"}:
		return "excel"
	if suffix in {".eml"}:
		return "email"
	if suffix in {".htm", ".html"}:
		return "htm"
	if suffix == ".txt":
		return _sniff_txt_type(file_path)
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


def _ensure_htm_file_type_allowed() -> None:
	"""Ensure documents.file_type constraint accepts htm."""
	global _FILE_TYPE_CONSTRAINT_READY
	if _FILE_TYPE_CONSTRAINT_READY:
		return

	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_file_type_check")
			cur.execute(
				"""
				ALTER TABLE documents
				ADD CONSTRAINT documents_file_type_check
				CHECK (file_type IN ('pdf', 'excel', 'email', 'htm', 'unknown'))
				"""
			)
		conn.commit()
		_FILE_TYPE_CONSTRAINT_READY = True
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
					"""
					SELECT id::text FROM documents
					WHERE file_hash = %s
					AND status NOT IN ('failed')
					LIMIT 1
					""",
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


def _update_document_filename(document_id: str, filename: str) -> None:
	"""Update stored document display filename."""
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"""
				UPDATE documents
				SET filename = %s
				WHERE id = %s::uuid
				""",
				(filename, document_id),
			)
		conn.commit()
	finally:
		release_connection(conn)


def _sanitize_label(value: str) -> str:
	"""Normalize text for compact display labels."""
	label = " ".join(str(value or "").split())
	label = re.sub(r"[\x00-\x1F\x7F]", "", label)
	return label.strip()


def _truncate_label(value: str, max_len: int) -> str:
	"""Truncate labels without breaking readability."""
	cleaned = _sanitize_label(value)
	if len(cleaned) <= max_len:
		return cleaned
	return cleaned[: max_len - 1].rstrip() + "..."


def _email_summary_filename(parsed: dict, fallback_filename: str) -> str:
	"""Build a meaningful display name for email-like documents."""
	subject = _truncate_label(str(parsed.get("subject", "")), 80)
	sender = _truncate_label(str(parsed.get("sender", "")), 40)
	date = _truncate_label(str(parsed.get("date", "")), 24)

	parts: list[str] = []
	if subject:
		parts.append(subject)
	if sender:
		parts.append("from %s" % sender)
	if date:
		parts.append(date)

	if not parts:
		return fallback_filename
	return "Email: %s" % " | ".join(parts)


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
	_ensure_htm_file_type_allowed()

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
		parse_timeout = _parse_timeout_for_file(file_path, file_type)
		parse_method = ""
		if file_type == "pdf":
			parsed = await asyncio.wait_for(asyncio.to_thread(parse_pdf, file_path), timeout=parse_timeout)
			parse_error = parsed.get("error")
			parse_method = str(parsed.get("metadata", {}).get("parse_method", ""))
		elif file_type == "htm":
			parsed = await asyncio.wait_for(
				asyncio.to_thread(parse_htm, file_path),
				timeout=_parse_timeout_for_file(file_path, "htm"),
			)
			parse_error = parsed.get("error")
			parse_method = str(parsed.get("metadata", {}).get("parse_method", ""))
		elif file_type == "excel":
			parsed = await asyncio.wait_for(asyncio.to_thread(parse_excel, file_path), timeout=parse_timeout)
			parse_error = parsed[0].get("error") if parsed and isinstance(parsed[0], dict) else None
		else:
			parsed = await asyncio.wait_for(asyncio.to_thread(parse_email, file_path), timeout=parse_timeout)
			parse_error = parsed.get("error")
			summary_name = _email_summary_filename(parsed, fallback_filename=filename)
			if summary_name != filename:
				_update_document_filename(document_id, summary_name)
				filename = summary_name

		if parse_error:
			_update_document_status(document_id, status="failed", error=str(parse_error))
			return {
				"document_id": document_id,
				"filename": filename,
				"file_type": file_type,
				"status": "failed",
				"error": str(parse_error),
			}

		if isinstance(parsed, dict) and parsed.get("skipped") is True:
			skip_reason = "content skipped by parser"
			_update_document_status(document_id, status="skipped", error=skip_reason)
			return {
				"document_id": document_id,
				"filename": filename,
				"file_type": file_type,
				"chunk_count": 0,
				"field_count": 0,
				"status": "skipped",
				"skipped": True,
				"error": skip_reason,
			}

		chunks = chunk_document(parsed, file_type)
		if len(chunks) > 100:
			print(
				f"[INFO] {filename}: {len(chunks)} chunks — using batched extraction "
				f"(batches of {25}, ~{round(len(chunks) / 25)} batches)"
			)
		if not chunks:
			error_message = "no chunks generated"
			all_excel_sheets_skipped = (
				file_type == "excel"
				and isinstance(parsed, list)
				and len(parsed) > 0
				and all(isinstance(item, dict) and item.get("skipped") is True for item in parsed)
			)
			if all_excel_sheets_skipped:
				_update_document_status(document_id, status="skipped", error=error_message)
				return {
					"document_id": document_id,
					"filename": filename,
					"file_type": file_type,
					"chunk_count": 0,
					"field_count": 0,
					"status": "skipped",
					"skipped": True,
					"error": error_message,
				}

			_update_document_status(document_id, status="failed", error=error_message)
			return {
				"document_id": document_id,
				"filename": filename,
				"file_type": file_type,
				"chunk_count": 0,
				"field_count": 0,
				"status": "failed",
				"error": error_message,
			}

		for chunk in chunks:
			chunk["id"] = str(uuid4())

		_update_document_status(document_id, status="processing")

		embed_extract_timeout = max(EMBED_EXTRACT_TIMEOUT_SECONDS, int(parse_timeout * 1.8))
		_, extracted_fields = await asyncio.wait_for(
			asyncio.gather(
				embed_and_store_chunks(document_id, chunks, file_type),
				run_extraction(document_id, chunks, file_type),
			),
			timeout=embed_extract_timeout,
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
			"parse_method": parse_method,
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


async def ingest_file_with_timeout(file_path: str, timeout_seconds: int | None = None) -> dict:
	"""Run ingest_file with a hard timeout so one stuck file cannot block batches."""
	filename = Path(file_path).name
	file_type = detect_file_type(file_path)
	effective_timeout = timeout_seconds if timeout_seconds is not None else _ingest_timeout_for_file(file_path, file_type)
	try:
		return await asyncio.wait_for(ingest_file(file_path), timeout=effective_timeout)
	except asyncio.TimeoutError:
		return {
			"filename": filename,
			"file_type": file_type,
			"chunk_count": 0,
			"field_count": 0,
			"status": "failed",
			"error": "timeout after %ss" % effective_timeout,
		}


async def ingest_folder(folder_path: str) -> list[dict]:
	"""Ingest all files in a folder sequentially and continue on individual errors."""
	results: list[dict] = []
	folder = Path(folder_path)

	for path in sorted(folder.iterdir()):
		if not path.is_file():
			continue
		try:
			result = await ingest_file_with_timeout(str(path))
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
