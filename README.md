# Vantage

Enterprise document intelligence and RAG pipeline for mixed files (PDFs, Excel, emails), built for the Zaigo demo submission.

## Prerequisites
- Python 3.10+
- Supabase account and project
- OpenAI API key

## Setup And Run
1. Clone and open the repo:
```bash
git clone <your-repo-url>
cd vantage
```
2. Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. Create your environment file:
```bash
cp .env.example .env
```
5. Update .env values:
- OPENAI_API_KEY: your key (sk-...)
- DATABASE_URL: Supabase transaction pooler URI (port 6543)
- DATABASE_DIRECT_URL: Supabase direct URI (port 5432)
- CHROMA_PATH: local Chroma persistence path (example: ./chroma_db)
- DATA_DIR: data root path (example: ./data)
- POOL_MIN / POOL_MAX: pool sizes
6. Initialize schema in Supabase:
```bash
python db.py
```
7. Launch the app:
```bash
python main.py
```

## Demo Data
### 10-K PDFs (SEC EDGAR)
- Source: SEC EDGAR browser: https://www.sec.gov/cgi-bin/browse-edgar
- Download annual reports (10-K) for public companies.
- Suggested mix: 5 to 6 companies across sectors, 2 to 6 reports each.

### Excel Files
- Export public financial tables (for example from Macrotrends) and save as .xlsx.
- Create a few intentionally messy sheets:
  - merged headers
  - blank rows
  - multiple sheets with one empty sheet

### Email Files
- Create plain text files (.txt or .eml) with this structure:
  - Subject: ...
  - From: ...
  - Date: ...
  - blank line
  - body text (2 to 3 paragraphs)
- Include edge cases:
  - one with near-empty body
  - one short thread with multiple From: boundaries

## Demo Flow
1. Go to Ingest tab.
2. Paste a folder path with your mixed files (or upload multiple files).
3. Click Ingest and watch per-file progress.
4. Go to Query tab.
5. Ask natural language questions.
6. Validate grounded answers using source citations and excerpts.

## Example Queries

After ingesting your documents, try these in the Query tab:

- "What is [company name]'s revenue for fiscal year 2023?"
- "What were the key risks mentioned across all annual reports?"
- "What action items were assigned in the board emails?"
- "Which companies reported EBITDA above $1B?"
- "What decisions were made in the most recent board update?"
- "Summarize the financial performance across all ingested documents."

These are designed to work across PDFs, Excel, and email files together — showing cross-document retrieval in a single answer.

## File Map
- architecture.md: system architecture, schema, costs, and scale path.
- cache.py: embedding cache read/write with SHA-256 keys.
- chunk.py: type-aware chunking with token guards.
- config.py: env loading and required configuration constants.
- copilot.md: implementation rules and coding constraints.
- db.py: Supabase pool helpers and schema initialization.
- embed.py: cache-first batch embeddings and Chroma writes.
- extract.py: GPT field extraction and summarization.
- ingest.py: ingest orchestrator for detect/parse/chunk/embed/extract/persist.
- main.py: Gradio UI wiring for ingest and query.
- parse/pdf.py: PDF parsing with scanned fallback.
- parse/excel.py: Excel parsing with merged-cell forward fill.
- parse/email.py: plain text email parsing with skip guards.
- requirements.txt: Python dependencies.
- retrieval.py: retrieval pipeline, grounded answer generation, and query logging.
- retry.py: retry decorator, safe JSON parsing, reusable OpenAI call.
- schema.sql: PostgreSQL schema and indexes.
- seed.py: CLI batch seeding helper that runs ingest_folder.
- states.md: milestone checklist for project states.

## Latency And Cost (50-100 Documents)
| Stage | Time estimate | Cost estimate |
|---|---|---|
| PDF parsing (50 PDFs, 10 pages avg) | ~15-30s total | $0 |
| Excel parsing (20 files) | ~5s total | $0 |
| Email parsing (30 emails) | ~2s total | $0 |
| Embedding (500 chunks, batch) | ~8-12s | ~$0.004 |
| Field extraction (500 chunks, concurrent) | ~45-90s | ~$0.05-0.10 |
| Query (single) | ~1.5-3s | ~$0.002 |
| Total ingest (100 docs) | ~2-3 min | < $0.15 |

## Production Delta
For production hardening, move from demo architecture to:
1. pgvector in Supabase instead of local ChromaDB.
2. Celery + Redis for queue-based background ingest and extraction.
3. S3-compatible object storage for raw and processed files.
4. Textract or equivalent OCR pipeline for scanned PDFs at scale.
5. Row Level Security (RLS) with tenant-scoped org_id access controls.

## Quick Demo Commands
Initialize DB and run UI:
```bash
python db.py
python main.py
```
Run CLI seed ingest for a folder:
```bash
python seed.py ./data/raw
```
