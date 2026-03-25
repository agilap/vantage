# Vantage — Project States

Tracks the build state at each checkpoint. Each state is a working, demoable milestone. Update the Current State line as you progress.

---

## State 0 — Repo Initialized

**What exists:**
- `vantage/` folder with full structure: `parse/`, `data/raw/`, `data/processed/`, `docs/`
- `config.py` loading all 7 env vars, raising `ValueError` on missing keys
- `requirements.txt` with all dependencies
- `.env.example` with all 7 vars documented
- Empty placeholder files for all modules

**What works:**
- `python config.py` prints all 7 config values without error

**Commit:**
```
chore: initialize vantage repo, folder structure, env config, requirements
```

---

## State 1 — Database Ready

**What exists:**
- `db.py` with `get_pool()`, `get_connection()`, `release_connection()`, `init_db()`
- `schema.sql` with all 5 tables and all indexes
- `init_db()` uses `DATABASE_DIRECT_URL` (port 5432), closes connection immediately after

**What works:**
- `python db.py` connects to Supabase and creates all 5 tables without error
- Tables visible in Supabase dashboard: `documents`, `chunks`, `extracted_fields`, `query_log`, `embedding_cache`
- All indexes created and visible

**Commit:**
```
feat(db): add supabase connection pool, schema init, all tables and indexes
```

---

## State 2 — Retry and Cache Layer

**What exists:**
- `retry.py` with `with_retry()` decorator, `safe_parse()`, `call_openai()`
- `cache.py` with `get_content_hash()`, `get_cached_embedding()`, `store_embedding()`

**What works:**
- `@with_retry` correctly retries a failing async function up to 3 times with exponential backoff
- `safe_parse()` correctly strips JSON fences and returns `[]` or `{}` on parse failure
- `store_embedding()` writes to Supabase, `get_cached_embedding()` returns the list on next call
- `get_cached_embedding()` returns `None` on cache miss

**Commit:**
```
feat(infra): add retry decorator, safe_parse, call_openai, and embedding cache
```

---

## State 3 — All Parsers Working

**What exists:**
- `parse/pdf.py` with `parse_pdf()` — pdfplumber primary, pypdf fallback, scanned detection
- `parse/excel.py` with `parse_excel()` — multi-sheet, merged cell forward-fill, empty sheet skip
- `parse/email.py` with `parse_email()` — header extraction, short body guard

**What works:**
- `parse_pdf("data/raw/sample.pdf")` returns dict with `text`, `pages`, `metadata`, `parse_method`
- `parse_pdf()` on a scanned PDF returns dict with `parse_method: "pypdf_fallback"` — does not crash
- `parse_pdf()` on a corrupt file returns dict with `error` key — does not crash
- `parse_excel("data/raw/sample.xlsx")` returns list of sheet dicts with headers and rows
- `parse_excel()` on a file with merged cells returns correctly forward-filled rows
- `parse_excel()` on a file with an empty sheet returns list with that sheet marked `skipped`
- `parse_email("data/raw/sample.txt")` returns dict with `body`, `subject`, `sender`, `date`
- `parse_email()` on a < 20 char body returns dict with `skipped: True` — does not crash

**Commit:**
```
feat(parse): add pdf, excel, and email parsers with edge case handling
```

---

## State 4 — Chunking Pipeline Working

**What exists:**
- `chunk.py` with `chunk_document()`, `estimate_tokens()`
- Type-aware strategies: section-aware for PDF, row-group for Excel, per-email for email

**What works:**
- `chunk_document(parsed_pdf, "pdf")` returns list of chunks, each ≤ 8000 token estimate
- PDF chunks split on section headers where present, fall back to 500-word windows with 50-word overlap
- Excel chunks always include column headers at the top of each chunk
- Email chunks: one chunk per email, split by sender boundary for threads
- No empty chunks returned — guard is enforced
- Chunks exceeding 8000 token estimate are split further automatically

**Commit:**
```
feat(chunk): add type-aware chunking with token guard and header preservation
```

---

## State 5 — Embedding and Vector Store Working

**What exists:**
- `embed.py` with `embed_batch()` and `embed_and_store_chunks()`
- ChromaDB collection `vantage_docs` with cosine distance

**What works:**
- `embed_batch(["text a", "text b"])` returns list of two 1536-length float lists
- Second call with same text hits cache — confirmed by API call count
- `embed_and_store_chunks(meeting_id, chunks)` stores all chunks in ChromaDB with correct metadata
- ChromaDB collection queryable by `document_id` filter

**Commit:**
```
feat(embed): add batch embedding with cache and chromadb storage
```

---

## State 6 — Field Extraction Working

**What exists:**
- `extract.py` with `extract_fields()`, `summarize_chunk()`, `run_extraction()`
- P-02 (Field Extractor) and P-04 (Chunk Summarizer) prompts implemented
- `run_extraction()` uses `asyncio.gather()` across all chunks

**What works:**
- `extract_fields(chunk, "pdf")` returns list of dicts with `field_name`, `field_value`, `confidence`
- Fields extracted from a 10-K PDF chunk include at minimum: `company_name`, `fiscal_year`, `revenue`
- `run_extraction()` on 10 chunks completes faster than 10 sequential calls (concurrency confirmed by timing)
- `summarize_chunk()` returns a single clean sentence
- `safe_parse()` handles a malformed JSON response without crashing

**Commit:**
```
feat(extract): add concurrent gpt field extraction and chunk summarizer
```

---

## State 7 — Retrieval and Query Answering Working

**What exists:**
- `retrieval.py` with `query_documents()` and `get_document_fields()`
- Full RAG loop: embed query → ChromaDB → Supabase join → GPT answer → log

**What works:**
- `query_documents("What is Apple's revenue for 2023?")` returns a dict with `answer`, `sources`, `latency_ms`
- Answer is grounded in retrieved chunks — not hallucinated
- Sources include correct filename and chunk excerpt
- Queries below cosine threshold 0.3 are filtered out
- Query + response + latency logged to `query_log` table in Supabase
- `get_document_fields("some-uuid")` returns all extracted fields for that document

**Commit:**
```
feat(retrieval): add full rag query loop with grounded answers, source citations, and logging
```

---

## State 8 — Ingest Orchestrator Working

**What exists:**
- `ingest.py` with `detect_file_type()`, `check_duplicate()`, `ingest_file()`, `ingest_folder()`
- Full pipeline per file: detect → parse → chunk → embed + extract (concurrent) → bulk write → status update
- Duplicate detection via SHA-256 file hash

**What works:**
- `ingest_file("data/raw/sample.pdf")` runs end-to-end without error, status transitions to `done`
- `ingest_file()` on a duplicate file returns existing document id without re-processing
- `ingest_file()` on an unknown file type sets status `skipped`
- `ingest_folder("data/raw/")` processes all recognized files, returns result list
- On any failure: status set to `failed`, error stored, exception re-raised
- Chunks and fields bulk-inserted in a single transaction per document

**Commit:**
```
feat(ingest): wire full ingest pipeline with duplicate detection and bulk writes
```

---

## State 9 — UI Working

**What exists:**
- `main.py` with `gr.Blocks()` layout
- Tab 1 — Ingest: multi-file upload + folder path + Ingest button + per-file progress
- Tab 2 — Query: text input + Submit + answer + sources table
- `db.init_db()` called once at startup

**What works:**
- Upload 3 files → each shows "Parsing… Chunking… Embedding… Extracting… Done."
- Summary table appears after ingest: filename, type, chunks, fields extracted, status
- Query tab: type a question → answer streams in → sources table shows filename + excerpt
- Duplicate file upload shows "Already ingested" without re-processing
- Failed file shows error message in the status column — UI does not crash

**Commit:**
```
feat(ui): add gradio ingest and query interface with streaming progress
```

---

## State 10 — Demo Ready

**What exists:**
- 50–100 mixed files ingested: 10-K PDFs, Excel earnings models, board update emails
- Edge cases tested: scanned PDF, merged-cell Excel, empty email, duplicate upload
- README written with setup, run instructions, and demo flow
- All env vars documented in `.env.example`

**What works:**
- Full demo flow: ingest folder → query "What companies have EBITDA above $5B?" → grounded answer with sources
- Scanned PDF ingested with `pypdf_fallback` — does not crash, partially extracted
- Duplicate file upload handled silently
- OpenAI timeout after retries: document marked `failed`, error shown in UI
- `query_log` table in Supabase shows all queries with latency

**Commit:**
```
chore: finalize demo data, edge case testing, and readme for submission
```

---

## Current State

```
CURRENT: State 0 — Repo Initialized
```
