import hashlib
import json

from db import get_connection, release_connection


def get_content_hash(text: str) -> str:
	"""Return SHA-256 hex digest for cache keying."""
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_cached_embedding(text: str) -> list | None:
	"""Fetch a cached embedding by text hash or return None."""
	content_hash = get_content_hash(text)
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT embedding FROM embedding_cache WHERE content_hash = %s",
				(content_hash,),
			)
			row = cur.fetchone()
		if row is None:
			return None

		embedding_value = row[0]
		if isinstance(embedding_value, list):
			return embedding_value
		if isinstance(embedding_value, str):
			parsed = json.loads(embedding_value)
			return parsed if isinstance(parsed, list) else None
		return None
	finally:
		release_connection(conn)


def store_embedding(text: str, embedding: list) -> None:
	"""Store an embedding in cache if its hash does not already exist."""
	content_hash = get_content_hash(text)
	conn = get_connection()
	try:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO embedding_cache (content_hash, embedding)
				VALUES (%s, %s::jsonb)
				ON CONFLICT (content_hash) DO NOTHING
				""",
				(content_hash, json.dumps(embedding)),
			)
		conn.commit()
	finally:
		release_connection(conn)
