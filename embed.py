from uuid import uuid4

import chromadb
from openai import AsyncOpenAI

import config
from cache import get_cached_embedding, store_embedding


client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
collection = chroma_client.get_or_create_collection(
	name="vantage_docs",
	metadata={"hnsw:space": "cosine"},
)


async def embed_batch(texts: list[str]) -> list[list[float]]:
	"""Embed texts with cache-first behavior and preserve input ordering."""
	if not texts:
		return []

	results: list[list[float] | None] = [None] * len(texts)
	misses_by_text: dict[str, list[int]] = {}

	for index, text in enumerate(texts):
		cached = get_cached_embedding(text)
		if cached is None:
			misses_by_text.setdefault(text, []).append(index)
		else:
			results[index] = cached

	if misses_by_text:
		unique_miss_texts = list(misses_by_text.keys())
		response = await client.embeddings.create(
			model="text-embedding-3-small",
			input=unique_miss_texts,
		)
		for miss_offset, embedding_data in enumerate(response.data):
			text_value = unique_miss_texts[miss_offset]
			embedding = embedding_data.embedding
			store_embedding(text_value, embedding)
			for target_index in misses_by_text[text_value]:
				results[target_index] = embedding

	return [embedding if embedding is not None else [] for embedding in results]


async def embed_and_store_chunks(document_id: str, chunks: list[dict], file_type: str) -> None:
	"""Embed all chunk content and add to ChromaDB in a single batch call."""
	if not chunks:
		return

	documents = [str(chunk.get("content", "")) for chunk in chunks]
	embeddings = await embed_batch(documents)

	ids = [f"{document_id}:{chunk.get('chunk_index')}:{uuid4().hex}" for chunk in chunks]
	metadatas = [
		{
			"document_id": document_id,
			"file_type": file_type,
			"chunk_index": chunk.get("chunk_index"),
			"chunk_type": chunk.get("chunk_type"),
		}
		for chunk in chunks
	]

	collection.add(
		ids=ids,
		documents=documents,
		embeddings=embeddings,
		metadatas=metadatas,
	)
