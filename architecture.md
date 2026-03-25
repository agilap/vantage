# Vantage — System Architecture

## Overview

Vantage is an enterprise document intelligence pipeline. It ingests mixed file types (PDFs, Excel, emails), parses and chunks them using type-aware strategies, extracts structured fields via a chained LLM sequence, stores everything in PostgreSQL and ChromaDB, and exposes a natural language query interface backed by semantic retrieval.

Designed for a PE firm ingesting 50–100 documents across a portfolio. Scales to thousands of documents without architectural change.

---

## Stack

| Layer | MVP (now) | Scale-up path |
|---|---|---|
| UI | Gradio `gr.Blocks()` | FastAPI + React frontend |
| PDF parsing | `pdfplumber` (primary) + `pypdf` (fallback) | Textract for scanned docs |
| Excel parsing | `pandas` + `openpyxl` | Spark for multi-GB workbooks |
| Email parsing | Plain text + P-01 cleanup | MIME parser for full `.eml` |
| Chunking | Type-aware: section / row-group / paragraph | Semantic chunking via embeddings |
| Embeddings | OpenAI `text-embedding-3-small`, batched | Cohere or local `all-MiniLM-L6-v2` |
| Embedding cache | Supabase `embedding_cache` table + SHA-256 | Redis for hot cache layer |
| Vector store | ChromaDB (local persistent) | pgvector (same Supabase instance) |
| Field extraction | OpenAI `gpt-4o-mini`, async, per chunk | Fine-tuned extraction model |
| Query answering | OpenAI `gpt-4o-mini`, RAG-grounded | Swap model, add fallback provider |
| Task queue | asyncio (MVP) | Celery + Redis |
| Database | Supabase (PostgreSQL) via `ThreadedConnectionPool` | Read replicas, partitioning |
| Storage | Local filesystem / `./data/` | S3-compatible object store |
| Dataset | 50–100 mixed enterprise documents | Live file upload, webhook ingestion |

---

## File Structure

```
vantage/
├── main.py                   # Gradio UI — entry point
├── ingest.py                 # Orchestrator: detect → parse → chunk → embed → extract
├── parse/
│   ├── __init__.py
│   ├── pdf.py                # pdfplumber primary, pypdf fallback, edge case guards
│   ├── excel.py              # pandas + openpyxl, multi-sheet, merged cell handling
│   └── email.py              # Plain text cleanup, header extraction
├── chunk.py                  # Type-aware chunking strategies
├── embed.py                  # Batch embedding with cache-first behavior
├── extract.py                # GPT field extraction per chunk
├── retrieval.py              # ChromaDB query + Supabase join + answer generation
├── db.py                     # Connection pool + schema init
├── cache.py                  # Embedding cache (SHA-256 + Supabase)
├── retry.py                  # Retry decorator, safe_parse, call_openai
├── config.py                 # Env vars and constants
├── requirements.txt
├── .env
├── .env.example
├── data/
│   ├── raw/                  # Uploaded source files
│   └── processed/            # Parsed text output (optional debug)
└── docs/
    ├── architecture.md
    ├── copilot.md
    ├── states.md
    └── build_prompts.md
```

---

## Supabase Setup

1. Go to [supabase.com](https://supabase.com) → New project
2. **Settings → Database → Connection string → URI**
   - **Transaction pooler** (port `6543`) → all runtime app queries → `DATABASE_URL`
   - **Direct connection** (port `5432`) → `init_db()` schema migrations only → `DATABASE_DIRECT_URL`
3. Copy both into `.env`:
   ```
   DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   DATABASE_DIRECT_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres
   ```
4. `pgcrypto` is pre-enabled in Supabase — `gen_random_uuid()` works without `CREATE EXTENSION`
5. SSL is handled automatically by `psycopg2` for `*.supabase.co` hosts

---

## Data Flow

```
INPUT (file upload via Gradio OR bulk folder drop)
        │
        ▼
[ INGEST ORCHESTRATOR — ingest.py ]
  1. Detect file type → route to correct parser
  2. Write document record to Supabase (status: pending)
  3. Parse raw text + metadata from file
  4. Apply type-aware chunking strategy
  5. Embed chunks in batch (cache-first)
  6. Store chunks in ChromaDB with metadata
  7. Run GPT field extraction per chunk
  8. Bulk write chunks + extracted fields to Supabase
  9. Update document status → done
        │
        ▼
[ QUERY INTERFACE — retrieval.py ]
  1. Embed the user query (cache-first)
  2. Query ChromaDB top-k similar chunks
  3. Fetch full chunk content + document metadata from Supabase
  4. Rerank by relevance score (simple cosine threshold)
  5. Pass retrieved chunks + query to GPT answer generator
  6. Return grounded answer + source citations
  7. Log query + response + latency to Supabase
        │
        ▼
OUTPUT (Gradio streams answer + shows source documents)
```

---

## Chunking Strategy (by file type)

This is the core RAG design decision. Different file types require different chunking to preserve semantic units.

| File type | Strategy | Chunk size | Rationale |
|---|---|---|---|
| PDF — text | Section-aware: split on headings (`##`, `SECTION`, line breaks + caps) | ~400–600 words | Preserves logical sections; decisions don't span sections |
| PDF — table-heavy | Row-group chunking: every 10–15 rows as one chunk | ~300 words | Tables are dense; smaller chunks reduce noise |
| PDF — scanned | Fall back to `pypdf` OCR text, paragraph split | ~300 words | OCR is noisy; smaller chunks reduce hallucination |
| Excel | Row-group: 20 rows per chunk, include column headers in every chunk | ~200–400 words | Headers must repeat so LLM knows column meaning |
| Email | Single chunk per email (emails are short) | Whole email | Splitting emails destroys context |
| Email thread | Split by sender boundary | Per message | Each message is a distinct utterance |

---

## PostgreSQL Schema (Supabase)

Run once via `python db.py` against **direct connection** (port 5432).

```sql
-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL CHECK (file_type IN ('pdf', 'excel', 'email', 'unknown')),
    source_path     TEXT,
    page_count      INTEGER,
    sheet_count     INTEGER,
    status          TEXT DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'done', 'failed', 'skipped')),
    error           TEXT,
    word_count      INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_status    ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_file_type ON documents(file_type);
CREATE INDEX IF NOT EXISTS idx_documents_created   ON documents(created_at);

-- Chunks table
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL,
    chunk_type      TEXT,
    token_estimate  INTEGER,
    metadata        JSONB,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document    ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type  ON chunks(chunk_type);

-- Extracted fields table
CREATE TABLE IF NOT EXISTS extracted_fields (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id        UUID REFERENCES chunks(id) ON DELETE CASCADE,
    field_name      TEXT NOT NULL,
    field_value     TEXT,
    confidence      TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fields_document   ON extracted_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_fields_field_name ON extracted_fields(field_name);

-- Query log table
CREATE TABLE IF NOT EXISTS query_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query           TEXT NOT NULL,
    response        TEXT,
    source_doc_ids  TEXT[],
    chunk_ids       TEXT[],
    latency_ms      INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);

-- Embedding cache
CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash    TEXT PRIMARY KEY,
    embedding       JSONB NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

---

## Connection Pool Pattern

```python
# db.py
import psycopg2.pool
import config

_pool = None

def get_pool():
    """Return singleton ThreadedConnectionPool — Supabase transaction pooler."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=config.POOL_MIN,
            maxconn=config.POOL_MAX,
            dsn=config.DATABASE_URL      # port 6543
        )
    return _pool

def get_connection():
    """Acquire connection from pool."""
    return get_pool().getconn()

def release_connection(conn):
    """Return connection to pool."""
    get_pool().putconn(conn)

def init_db():
    """Create schema via direct connection (port 5432) — run once at startup."""
    import psycopg2
    conn = psycopg2.connect(dsn=config.DATABASE_DIRECT_URL)
    try:
        with conn.cursor() as cur:
            with open("schema.sql") as f:
                cur.execute(f.read())
        conn.commit()
    finally:
        conn.close()
```

Always release in `finally`:
```python
conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT ...", (%s,))
    conn.commit()
finally:
    release_connection(conn)
```

---

## Async OpenAI Pattern

```python
# All LLM calls use AsyncOpenAI
from openai import AsyncOpenAI
import config

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# Concurrent extraction across chunks
results = await asyncio.gather(*[
    extract_fields(chunk) for chunk in chunks
])
```

---

## Edge Case Handling

| Edge case | Detection | Handling |
|---|---|---|
| Scanned PDF (no text layer) | `pdfplumber` returns < 50 chars/page | Fall back to `pypdf`, flag as `scanned`, log warning |
| Merged cells in Excel | `openpyxl` merge detection | Forward-fill merged values before row-grouping |
| Empty Excel sheet | 0 rows after header | Skip sheet, log as `skipped_sheet` in metadata |
| Email with no body | Body < 20 chars after strip | Skip, set status `skipped` |
| Password-protected PDF | `pdfplumber` raises `PdfReadError` | Catch, set status `failed`, log error |
| Duplicate file upload | SHA-256 hash of file bytes vs `documents` table | Return existing document id, skip re-ingestion |
| Chunk too long for embedding | Token estimate > 8191 | Split chunk further before embedding call |
| OpenAI timeout | `APITimeoutError` after retries | Set document status `failed`, store error, surface in UI |

---

## Prompt Structure

| ID | Name | File | Purpose |
|---|---|---|---|
| P-01 | Email Cleanup | `parse/email.py` | Remove noise, extract sender/date/subject |
| P-02 | Field Extractor | `extract.py` | Extract structured fields from any chunk type |
| P-03 | Query Answerer | `retrieval.py` | Grounded answer from retrieved chunks |
| P-04 | Chunk Summarizer | `extract.py` | One-sentence summary per chunk for metadata |

---

## Latency + Cost (50–100 documents)

| Stage | Time estimate | Cost estimate |
|---|---|---|
| PDF parsing (50 PDFs, 10 pages avg) | ~15–30s total | $0 |
| Excel parsing (20 files) | ~5s total | $0 |
| Email parsing (30 emails) | ~2s total | $0 |
| Embedding (500 chunks, batch) | ~8–12s | ~$0.004 |
| Field extraction (500 chunks, concurrent) | ~45–90s | ~$0.05–0.10 |
| Query (single) | ~1.5–3s | ~$0.002 |
| **Total ingest (100 docs)** | **~2–3 min** | **< $0.15** |

---

## Zaigo Capability Map

| Zaigo Requirement | How Vantage Covers It |
|---|---|
| Messy real-world data | PDFs (text + scanned), Excel (multi-sheet, merged cells), emails — all handled with type-aware parsing |
| Structured field extraction | GPT-4o-mini extracts named fields (company, revenue, EBITDA, decisions, owners) per chunk |
| Queryable interface | Semantic retrieval via ChromaDB + GPT-grounded answer with source citations |
| Chunking rationale | Section-aware (PDF), row-group with headers (Excel), whole-email (email) — different for each type |
| Edge case handling | Scanned PDF fallback, merged cell fill, duplicate detection, empty file skip, token limit guard |
| Latency + cost | Full 100-doc ingest < 3 min, < $0.15. Single query < 3s, < $0.002 |
| Production delta | pgvector migration, Celery queue, S3 storage, Textract for scanned PDFs, row-level security |

---

## Scale-Up Milestones

| When | What to add |
|---|---|
| > 500 documents | Enable pgvector in Supabase — drop ChromaDB dependency |
| > 10 concurrent users | Add Celery + Redis for ingest task queue |
| > 10k documents | Partition `chunks` table by `document_id` hash |
| Scanned PDFs at scale | AWS Textract or Azure Document Intelligence |
| Multi-tenant (multiple PE firms) | Add `org_id` to all tables, Supabase Row Level Security |
| Sensitive documents | Encryption at rest (Supabase), field-level encryption for financials |
| Audit trail | Append-only `audit_log` table on all writes |
