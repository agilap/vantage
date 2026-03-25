import asyncio

import openai
from openai import AsyncOpenAI

import config
from retry import call_openai, safe_parse, with_retry


client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


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
	user_prompt = f"File type: {file_type}\n\nChunk content:\n{chunk.get('content', '')}"
	response = await call_openai(client, system_prompt, user_prompt, max_tokens=1000)
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
	tasks = [extract_fields(chunk, file_type) for chunk in chunks]
	extracted_per_chunk = await asyncio.gather(*tasks)

	results: list[dict] = []
	for chunk, fields in zip(chunks, extracted_per_chunk):
		chunk_id = chunk.get("id", chunk.get("chunk_index"))
		if not isinstance(fields, list):
			continue
		for field in fields:
			if not isinstance(field, dict):
				continue
			enriched_field = dict(field)
			enriched_field["document_id"] = document_id
			enriched_field["chunk_id"] = chunk_id
			results.append(enriched_field)
	return results
