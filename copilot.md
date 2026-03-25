# Vantage — Copilot Instructions

Drop this file into your Cursor or Copilot context alongside `architecture.md` and `build_prompts.md` before writing any code.

---

## Project Summary

Vantage is an enterprise RAG pipeline. It ingests 50–100 mixed files (PDFs, Excel, emails), parses them with type-aware strategies, chunks them intelligently, extracts structured fields via GPT, stores everything in Supabase and ChromaDB, and answers natural language queries grounded in the document corpus.

Built for a PE firm managing portfolio company documents. Every design decision favours production-readiness and explainability.

---

## Tech Stack (do not suggest alternatives)

| Concern | Tool |
|---|---|
| UI | Gradio `gr.Blocks()` with streaming |
| PDF parsing | `pdfplumber` (primary), `pypdf` (fallback for scanned/corrupt) |
| Excel parsing | `pandas` + `openpyxl` |
| Email parsing | Plain text + P-01 cleanup via GPT |
| Chunking | Type-aware — see chunk.py spec below |
| Embeddings | `AsyncOpenAI`, `text-embedding-3-small`, batched |
| Embedding cache | Supabase `embedding_cache` + SHA-256 |
| Vector store | ChromaDB local persistent — cosine distance |
| Field extraction | `AsyncOpenAI`, `gpt-4o-mini`, concurrent per chunk |
| Query answering | `AsyncOpenAI`, `gpt-4o-mini`, RAG-grounded |
| Database | Supabase (PostgreSQL) via `psycopg2.pool.ThreadedConnectionPool` |
| Retry | Custom `@with_retry` async decorator in `retry.py` |
| Env | `python-dotenv`, `.env` at project root |

---

## Supabase Connection

Two URLs — both required in `.env`:

```
# Transaction pooler — all runtime queries (port 6543)
DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres

# Direct connection — init_db() schema migrations only (port 5432)
DATABASE_DIRECT_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres
```

- `DATABASE_URL` (port 6543) → `ThreadedConnectionPool` — all app queries
- `DATABASE_DIRECT_URL` (port 5432) → `init_db()` only, closes immediately after
- `pgcrypto` pre-enabled — no `CREATE EXTENSION` needed
- SSL handled automatically by `psycopg2`

---

## File Responsibilities

### `config.py`
- Load `.env` using `python-dotenv`
- Export constants only: `OPENAI_API_KEY`, `DATABASE_URL`, `DATABASE_DIRECT_URL`, `CHROMA_PATH`, `DATA_DIR`, `POOL_MIN`, `POOL_MAX`
- Raise a clear `ValueError` if any variable is missing — name the missing key
- Zero logic beyond loading and exporting

### `db.py`
- `get_pool()` → singleton `ThreadedConnectionPool(minconn, maxconn)` using `DATABASE_URL` (port 6543)
- `get_connection()` → acquire from pool
- `release_connection(conn)` → return to pool
- `init_db()` → connect via `DATABASE_DIRECT_URL` (port 5432), execute schema SQL, close immediately
- All callers: try/finally to release — never leave a connection open

### `retry.py`
- `with_retry(max_attempts=3, base_delay=1.0, exceptions=(...))` → async decorator, exponential backoff
- `safe_parse(response, expected_type="array") -> list | dict` → strip JSON fences, fallback to [] or {}
- `call_openai(client, system_prompt, user_prompt, max_tokens=1000)` → single reusable async call, `gpt-4o-mini`, temperature 0.2
- All three live here — imported from `retry.py` by every other file

### `cache.py`
- `get_content_hash(text: str) -> str` → SHA-256 hex digest
- `get_cached_embedding(text: str) -> list | None` → SELECT from `embedding_cache`, return list or None
- `store_embedding(text: str, embedding: list) -> None` → INSERT with ON CONFLICT DO NOTHING
- Use pool on every call, release in finally

### `parse/pdf.py`
- `parse_pdf(file_path: str) -> dict` → returns `{ text, pages, metadata, parse_method }`
- Primary: `pdfplumber` — extract text page by page, detect table-heavy pages
- Fallback: if `pdfplumber` returns < 50 chars/page on average, switch to `pypdf`
- Flag scanned PDFs: set `parse_method = "pypdf_fallback"` in returned dict
- Catch `FileNotFoundError`, `pdfplumber.PDFSyntaxError`, `pypdf.errors.PdfReadError` — return empty dict with `error` key
- Never crash — always return a dict

### `parse/excel.py`
- `parse_excel(file_path: str) -> list[dict]` → returns list of sheet dicts `{ sheet_name, rows, headers, metadata }`
- Use `openpyxl` to detect merged cells — forward-fill merged values before processing
- Skip sheets with 0 data rows after header — log as `skipped_sheet` in metadata
- Handle `openpyxl.utils.exceptions.InvalidFileException` → return empty list with error
- Never crash — always return a list

### `parse/email.py`
- `parse_email(file_path: str) -> dict` → returns `{ body, subject, sender, date, metadata }`
- For plain `.txt` emails: extract subject/from/date from first lines using simple string parsing
- Skip emails with body < 20 chars — return dict with `skipped: True`
- No GPT call in this file — cleanup happens in `extract.py` via P-01

### `chunk.py`
- `chunk_document(parsed: dict, file_type: str) -> list[dict]` → returns list of chunk dicts `{ content, chunk_index, chunk_type, token_estimate, metadata }`
- PDF chunks: split by section headers first; fall back to 500-word sliding window with 50-word overlap
- Excel chunks: 20 rows per chunk; prepend column headers to EVERY chunk
- Email chunks: one chunk per email; split by sender boundary for threads
- `estimate_tokens(text: str) -> int` → rough estimate: `len(text.split()) * 1.3`
- Guard: if any chunk exceeds 8000 token estimate, split it further before returning
- Never return empty content chunks

### `embed.py`
- `embed_batch(texts: list[str]) -> list[list[float]]` → async, cache-first, one API call for all misses
- `embed_and_store_chunks(document_id: str, chunks: list[dict]) -> None` → embed all chunks, store in ChromaDB with metadata: `document_id`, `file_type`, `chunk_index`, `chunk_type`
- ChromaDB collection: `vantage_docs`, cosine distance, `get_or_create_collection`
- Initialize ChromaDB client once at module level using `config.CHROMA_PATH`

### `extract.py`
- `extract_fields(chunk: dict, file_type: str) -> list[dict]` → async, P-02 prompt, returns list of `{ field_name, field_value, confidence }`
- `summarize_chunk(chunk: dict) -> str` → async, P-04 prompt, returns one-sentence summary
- `run_extraction(document_id: str, chunks: list[dict], file_type: str) -> list[dict]` → runs `extract_fields` concurrently across all chunks via `asyncio.gather`
- All functions decorated with `@with_retry(exceptions=(openai.RateLimitError, openai.APITimeoutError))`
- Use `safe_parse()` on all JSON responses

### `retrieval.py`
- `query_documents(query: str, n_results: int = 5) -> dict` → full async RAG pipeline
  1. Embed query (cache-first)
  2. Query ChromaDB for top n_results chunks
  3. Fetch full chunk content + document metadata from Supabase
  4. Filter chunks below cosine threshold (0.3)
  5. Call P-03 answer generator with retrieved chunks + query
  6. Log query + response + source_doc_ids + latency_ms to Supabase
  7. Return `{ answer, sources, latency_ms }`
- `get_document_fields(document_id: str) -> list[dict]` → fetch all extracted fields for a document from Supabase

### `ingest.py`
- `detect_file_type(file_path: str) -> str` → returns `'pdf'`, `'excel'`, `'email'`, or `'unknown'` based on extension + content sniff
- `check_duplicate(file_path: str) -> str | None` → SHA-256 hash of file bytes vs `documents` table — return existing `document_id` or None
- `ingest_file(file_path: str) -> dict` → full async pipeline for one file:
  1. `check_duplicate` → skip if already ingested
  2. Write document record, status: `pending`
  3. `detect_file_type`
  4. Route to correct parser
  5. `chunk_document`
  6. Update status: `processing`
  7. Concurrent: `embed_and_store_chunks` + `run_extraction` via `asyncio.gather`
  8. Bulk write chunks + fields to Supabase in single transaction
  9. Update status: `done`
  10. Return result dict
  On any failure: update status `failed`, store error, re-raise
- `ingest_folder(folder_path: str) -> list[dict]` → run `ingest_file` on all files, skip unknowns, return results list

### `main.py`
- `gr.Blocks()` layout only — no business logic
- Tab 1 — Ingest: file upload (multi-file) OR folder path input + Ingest button
- Tab 2 — Query: text input + Submit button
- Ingest output: progress per file, summary table (filename, type, chunks, fields extracted, status)
- Query output: answer text + sources table (filename, page/sheet, excerpt)
- Per-file progress: "Parsing… → Chunking… → Embedding… → Extracting fields… → Done."
- Call `db.init_db()` once at startup

---

## Coding Conventions

- All functions have type hints and a one-line docstring
- All OpenAI calls use `AsyncOpenAI` — never sync client
- All JSON responses go through `safe_parse()` from `retry.py`
- All SQL uses `%s` parameterized statements — never f-strings in SQL
- Bulk inserts use `executemany()` — never loop individual inserts
- ChromaDB collection always uses cosine distance
- Pool: always release in `finally`
- Parsers never crash — always return empty dict/list with an `error` key on failure
- `init_db()` always uses `DATABASE_DIRECT_URL` — never the pooler for DDL

---

## Scalability Rules

1. No new DB connection per request — always use the pool
2. No re-embedding the same text — always check cache first
3. No sequential embedding calls — always batch via `embed_batch()`
4. No sequential extraction calls — always `asyncio.gather()` across chunks
5. No individual row inserts — always `executemany()`
6. No hardcoded config values — always from `config.py`
7. No blocking the UI thread — all ingest logic runs async
8. No duplicate ingestion — always check file hash before processing
9. No empty chunks stored — guard in `chunk.py` before returning

---

## What Not to Do

- Do not use LangChain or LlamaIndex — build the chain manually
- Do not use SQLite — Supabase only
- Do not use sync `OpenAI` client — `AsyncOpenAI` throughout
- Do not combine extraction + answering into one prompt — they must stay separate
- Do not open a DB connection without releasing it
- Do not embed without checking cache first
- Do not insert rows one at a time in a loop
- Do not use `DATABASE_DIRECT_URL` for runtime queries
- Do not run `init_db()` through the connection pool
- Do not crash on a bad file — always catch and log

---

## Environment Variables

```
OPENAI_API_KEY=sk-...

# Supabase transaction pooler — all runtime queries (port 6543)
DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres

# Supabase direct connection — init_db() only (port 5432)
DATABASE_DIRECT_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres

CHROMA_PATH=./chroma_db
DATA_DIR=./data
POOL_MIN=2
POOL_MAX=10
```

---

## Demo Data (50–100 mixed files)

**PDFs (30–40 files):**
- SEC 10-K filings: download from [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar) — search any public company, download Annual Reports
- Target companies: 5–6 companies across different sectors
- Mix: text-heavy 10-Ks + table-heavy earnings supplements

**Excel (10–15 files):**
- Public earnings models: download from [Macrotrends](https://www.macrotrends.net) (export to CSV, save as .xlsx)
- Add 1–2 intentionally messy files: merged header cells, multiple sheets, blank rows mid-table

**Emails (10–20 files):**
- Write 10–15 short plain-text `.txt` files simulating board update emails
- Format: Subject / From / Date header lines, then 2–3 paragraph body
- Include 1–2 edge cases: email with no body, email with only an attachment note

**Target fields to extract:**
- `company_name`, `document_type`, `fiscal_year`, `revenue`, `ebitda`, `net_income`, `key_risks`, `decisions`, `action_items`, `mentioned_entities`
