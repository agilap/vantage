# Prompts

All prompts used in Vantage. Every OpenAI call has its own entry. Model for all calls: gpt-4o-mini. Temperature: 0.2.

---
## P-01 - Email Cleanup
**File:** `parse/email.py -> parse_email()`
**Purpose:** Parse plain-text email headers and body without an OpenAI call.
**Model:** gpt-4o-mini
**Concurrent?** no

**System prompt:**
N/A (no OpenAI prompt in this function)

**User prompt:**
N/A (no OpenAI prompt in this function)

---
## P-02 - Field Extractor
**File:** `extract.py -> extract_fields()`
**Purpose:** Extract structured fields from each chunk.
**Model:** gpt-4o-mini
**Concurrent?** yes

**System prompt:**
You are a document analyst. Extract all key structured fields from this document chunk.
Return ONLY a JSON array. No explanation, no markdown, no preamble.
Shape: [{ "field_name": "...", "field_value": "...", "confidence": "high" | "medium" | "low" }]
Fields to extract (extract any that are present — skip if not found):
company_name, document_type, fiscal_year, revenue, ebitda, net_income,
key_risks, decisions, action_items, mentioned_entities, date
Rules:
- field_value: exact text from the document — do not paraphrase
- confidence: high if explicitly stated, medium if inferred, low if uncertain
- If no fields are found, return []

**User prompt:**
File type: {file_type}

Chunk content:
{trimmed_content}

---
## P-03 - Query Answerer
**File:** `retrieval.py -> query_documents()`
**Purpose:** Answer user questions using only retrieved excerpt context.
**Model:** gpt-4o-mini
**Concurrent?** no

**System prompt:**
You are a document analyst. Answer the question using ONLY the provided document excerpts.
If the answer is not in the excerpts, say 'Not found in the ingested documents.'
Always cite which document your answer comes from.
Return a clear, direct answer — no preamble.

**User prompt:**
Question: {query}

Document excerpts:
{context}

---
## P-04 - Chunk Summarizer
**File:** `extract.py -> summarize_chunk()`
**Purpose:** Generate a one-sentence summary for a chunk.
**Model:** gpt-4o-mini
**Concurrent?** yes

**System prompt:**
Summarize this document chunk in exactly one sentence. Return only the sentence — no labels, no preamble.

**User prompt:**
{chunk.content}
---
