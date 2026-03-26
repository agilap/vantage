import asyncio

import openai
from openai import AsyncOpenAI

import config
from retry import call_openai, safe_parse, with_retry


client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
MAX_EXTRACTION_CHARS = 2600
# Keep concurrency at 15 to stay comfortably below provider RPM limits even with retries.
_EXTRACTION_SEMAPHORE = asyncio.Semaphore(15)
BATCH_SIZE = 25
BATCH_SLEEP_SECONDS = 2.0


@with_retry(exceptions=(openai.RateLimitError, openai.APITimeoutError))
async def extract_fields(chunk: dict, file_type: str) -> list[dict]:
	"""Extract structured fields from a chunk with concurrency cap."""
	async with _EXTRACTION_SEMAPHORE:
		system_prompt = """You are a document analyst. Extract all key structured fields from this document chunk.
Return ONLY a JSON array. No explanation, no markdown, no preamble.
Shape: [{ "field_name": "...", "field_value": "...", "confidence": "high" | "medium" | "low" }]
Fields to extract (extract any that are present — skip if not found):
company_name, document_type, fiscal_year, revenue, ebitda, net_income,
key_risks, decisions, action_items, mentioned_entities, date
Rules:
- field_value: exact text from the document — do not paraphrase
- confidence: high if explicitly stated, medium if inferred, low if uncertain
- If no fields are found, return []"""
		content = str(chunk.get("content", ""))
		trimmed_content = content[:MAX_EXTRACTION_CHARS]
		user_prompt = f"File type: {file_type}\n\nChunk content:\n{trimmed_content}"
		response = await call_openai(client, system_prompt, user_prompt, max_tokens=350)
		parsed = safe_parse(response, "array")
		return parsed if isinstance(parsed, list) else []


@with_retry(exceptions=(openai.RateLimitError, openai.APITimeoutError))
async def summarize_chunk(chunk: dict) -> str:
	"""Summarize a chunk in one sentence with concurrency cap."""
	async with _EXTRACTION_SEMAPHORE:
		system_prompt = (
			"Summarize this document chunk in exactly one sentence. "
			"Return only the sentence — no labels, no preamble."
		)
		user_prompt = str(chunk.get("content", ""))
		response = await call_openai(client, system_prompt, user_prompt, max_tokens=200)
		content = response.choices[0].message.content
		return str(content).strip() if content is not None else ""


@with_retry(exceptions=(openai.RateLimitError, openai.APITimeoutError))
async def run_extraction(document_id: str, chunks: list[dict], file_type: str) -> list[dict]:
	"""Run field extraction concurrently with rate-limit-aware batching."""
	if len(chunks) <= BATCH_SIZE:
		results = await asyncio.gather(
			*[extract_fields(chunk, file_type) for chunk in chunks],
			return_exceptions=True,
		)
	else:
		results = []
		for batch_start in range(0, len(chunks), BATCH_SIZE):
			batch = chunks[batch_start : batch_start + BATCH_SIZE]
			batch_results = await asyncio.gather(
				*[extract_fields(chunk, file_type) for chunk in batch],
				return_exceptions=True,
			)
			results.extend(batch_results)
			if batch_start + BATCH_SIZE < len(chunks):
				await asyncio.sleep(BATCH_SLEEP_SECONDS)

	all_fields: list[dict] = []
	for chunk, result in zip(chunks, results):
		if isinstance(result, Exception):
			print(f"[WARN] extract_fields failed for chunk {chunk.get('chunk_index')}: {result}")
			continue
		if not isinstance(result, list):
			continue
		chunk_id = str(chunk.get("id", ""))
		for field in result:
			if isinstance(field, dict) and field.get("field_name"):
				all_fields.append({**field, "document_id": document_id, "chunk_id": chunk_id})

	return all_fields
