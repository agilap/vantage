import asyncio

import openai
from openai import AsyncOpenAI

import config
from retry import call_openai, safe_parse, with_retry


client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
MAX_EXTRACTION_CHARS = 2600


@with_retry(exceptions=(openai.RateLimitError, openai.APITimeoutError))
async def extract_fields(chunk: dict, file_type: str) -> list[dict]:
	"""Extract structured fields from a document chunk."""
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
	"""Summarize a chunk into exactly one sentence."""
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
	"""Run extraction concurrently for all chunks and return a flat field list."""
	content_to_indexes: dict[str, list[int]] = {}
	for idx, chunk in enumerate(chunks):
		content_key = str(chunk.get("content", "")).strip()
		content_to_indexes.setdefault(content_key, []).append(idx)

	unique_chunks = [chunks[indexes[0]] for indexes in content_to_indexes.values()]
	tasks = [extract_fields(chunk, file_type) for chunk in unique_chunks]
	unique_results = await asyncio.gather(*tasks)

	extracted_per_chunk: list[list[dict]] = [[] for _ in chunks]
	for (content_key, indexes), fields in zip(content_to_indexes.items(), unique_results):
		if not isinstance(fields, list):
			fields = []
		for idx in indexes:
			extracted_per_chunk[idx] = fields

	results: list[dict] = []
	for chunk, fields in zip(chunks, extracted_per_chunk):
		chunk_id = chunk.get("id", chunk.get("chunk_index"))
		for field in fields:
			if not isinstance(field, dict):
				continue
			enriched_field = dict(field)
			enriched_field["document_id"] = document_id
			enriched_field["chunk_id"] = chunk_id
			results.append(enriched_field)
	return results
