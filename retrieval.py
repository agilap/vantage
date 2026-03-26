import time

import chromadb
from openai import AsyncOpenAI

import config
from db import get_connection, release_connection
from embed import embed_batch
from retry import call_openai


client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
collection = chroma_client.get_or_create_collection(
	name="vantage_docs",
	metadata={"hnsw:space": "cosine"},
)


def _log_query(
	query: str,
	response_text: str,
	source_doc_ids: list[str],
	chunk_ids: list[str],
	latency_ms: int,
) -> None:
	"""Write query telemetry to query_log, swallowing secondary logging failures."""
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO query_log (query, response, source_doc_ids, chunk_ids, latency_ms)
				VALUES (%s, %s, %s, %s, %s)
				""",
				(query, response_text, source_doc_ids, chunk_ids, latency_ms),
			)
		conn.commit()
	finally:
		release_connection(conn)


def _fetch_chunk_record(metadata: dict, fallback_chunk_id: str) -> dict | None:
	"""Fetch full chunk content and filename from Supabase using metadata identifiers."""
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			chunk_id = metadata.get("chunk_id") if isinstance(metadata, dict) else None
			if chunk_id:
				cur.execute(
					"""
					SELECT c.id::text, c.document_id::text, d.filename, c.chunk_index, c.content
					FROM chunks c
					JOIN documents d ON d.id = c.document_id
					WHERE c.id = %s
					LIMIT 1
					""",
					(chunk_id,),
				)
				row = cur.fetchone()
				if row:
					return {
						"chunk_id": row[0],
						"document_id": row[1],
						"filename": row[2],
						"chunk_index": row[3],
						"content": row[4],
					}

			document_id = metadata.get("document_id") if isinstance(metadata, dict) else None
			chunk_index = metadata.get("chunk_index") if isinstance(metadata, dict) else None
			if document_id is not None and chunk_index is not None:
				cur.execute(
					"""
					SELECT c.id::text, c.document_id::text, d.filename, c.chunk_index, c.content
					FROM chunks c
					JOIN documents d ON d.id = c.document_id
					WHERE c.document_id = %s::uuid AND c.chunk_index = %s
					LIMIT 1
					""",
					(str(document_id), int(chunk_index)),
				)
				row = cur.fetchone()
				if row:
					return {
						"chunk_id": row[0],
						"document_id": row[1],
						"filename": row[2],
						"chunk_index": row[3],
						"content": row[4],
					}

			if fallback_chunk_id:
				return {
					"chunk_id": fallback_chunk_id,
					"document_id": str(document_id) if document_id is not None else "",
					"filename": metadata.get("filename", "Unknown") if isinstance(metadata, dict) else "Unknown",
					"chunk_index": chunk_index,
					"content": "",
				}
			return None
	finally:
		release_connection(conn)


async def query_documents(query: str, n_results: int = 5) -> dict:
	"""Run the full retrieval pipeline and return answer, sources, and latency."""
	start = time.perf_counter()
	default_answer = "Not found in the ingested documents."
	answer = default_answer
	sources: list[dict] = []
	source_doc_ids: list[str] = []
	source_chunk_ids: list[str] = []
	log_response_text = default_answer

	try:
		query_embedding_list = await embed_batch([query])
		if not query_embedding_list:
			return {"answer": default_answer, "sources": [], "latency_ms": int((time.perf_counter() - start) * 1000)}

		chroma_result = collection.query(
			query_embeddings=[query_embedding_list[0]],
			n_results=n_results,
			include=["documents", "metadatas", "distances"],
		)

		ids = chroma_result.get("ids", [[]])[0] if chroma_result.get("ids") else []
		metadatas = chroma_result.get("metadatas", [[]])[0] if chroma_result.get("metadatas") else []
		distances = chroma_result.get("distances", [[]])[0] if chroma_result.get("distances") else []

		relevant_candidates: list[tuple[str, dict]] = []
		for idx, distance in enumerate(distances):
			if distance is None:
				continue
			if distance > 0.7:
				continue
			candidate_id = ids[idx] if idx < len(ids) else ""
			candidate_meta = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
			relevant_candidates.append((candidate_id, candidate_meta))

		for candidate_id, metadata in relevant_candidates:
			row = _fetch_chunk_record(metadata, candidate_id)
			if row is None:
				continue
			if not str(row.get("content", "")).strip():
				continue

			source_doc_ids.append(str(row.get("document_id", "")))
			source_chunk_ids.append(str(row.get("chunk_id", candidate_id)))
			sources.append(
				{
					"filename": row.get("filename", "Unknown"),
					"chunk_index": row.get("chunk_index"),
					"excerpt": row.get("content", ""),
				}
			)

		if sources:
			def _trim_excerpt(text: str, max_chars: int = 900) -> str:
				value = str(text or "")
				if len(value) <= max_chars:
					return value
				return value[: max_chars - 1].rstrip() + "..."

			context = "\n".join(
				"Document: %s\nExcerpt: %s\n---" % (source["filename"], _trim_excerpt(source["excerpt"]))
				for source in sources
			)
			system_prompt = (
				"You are a document analyst. Answer the question using ONLY the provided document excerpts.\n"
				"If the answer is not in the excerpts, say 'Not found in the ingested documents.'\n"
				"Always cite which document your answer comes from.\n"
				"Return a clear, direct answer — no preamble."
			)
			user_prompt = f"Question: {query}\n\nDocument excerpts:\n{context}"
			response = await call_openai(client, system_prompt, user_prompt, max_tokens=350)
			content = response.choices[0].message.content
			answer = str(content).strip() if content is not None else default_answer
			if not answer:
				answer = default_answer
		else:
			answer = default_answer

		log_response_text = answer
		return {
			"answer": answer,
			"sources": sources,
			"latency_ms": int((time.perf_counter() - start) * 1000),
		}
	except Exception as error:
		log_response_text = f"Error: {error}"
		return {
			"answer": default_answer,
			"sources": [],
			"latency_ms": int((time.perf_counter() - start) * 1000),
		}
	finally:
		latency_ms = int((time.perf_counter() - start) * 1000)
		try:
			_log_query(
				query=query,
				response_text=log_response_text,
				source_doc_ids=source_doc_ids,
				chunk_ids=source_chunk_ids,
				latency_ms=latency_ms,
			)
		except Exception:
			pass


def get_document_fields(document_id: str) -> list[dict]:
	"""Return all extracted fields for a document."""
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT field_name, field_value, confidence
				FROM extracted_fields
				WHERE document_id = %s::uuid
				ORDER BY created_at ASC
				""",
				(document_id,),
			)
			rows = cur.fetchall()

		return [
			{"field_name": row[0], "field_value": row[1], "confidence": row[2]}
			for row in rows
		]
	finally:
		release_connection(conn)
