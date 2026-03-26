# Prompting Strategy

### System Prompt (retrieval.py)
```text
You are a document analyst. Answer the question using ONLY the provided document excerpts.
If the answer is not in the excerpts, say 'Not found in the ingested documents.'
Always cite which document your answer comes from.
Return a clear, direct answer — no preamble.
```

"Answer using ONLY the provided document excerpts" prevents hallucination by grounding generation in retrieved context only. This keeps answers tied to evidence that can be shown back to the user instead of model priors.

"If the answer is not in the excerpts, say 'Not found in the ingested documents.'" gives the UI a stable sentinel for no-result behavior. A deterministic fallback string is much easier to detect than many possible free-form refusals.

"Always cite which document your answer comes from" makes every answer auditable. Because filename-level provenance is displayed in the interface, users can quickly verify or challenge the response.

"Return a clear, direct answer — no preamble" reduces token overhead and avoids verbose filler. Over many queries, this improves latency and controls inference cost.

### Field Extraction Prompt (extract.py)
```text
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
```

Structured JSON output is required so extraction can flow directly into downstream parsing and storage with minimal transformation. In this codebase, `safe_parse` in `retry.py` tolerates malformed model output and recovers safely, which prevents ingest from crashing when a single response is imperfect.

Confidence labels support downstream quality controls instead of all-or-nothing acceptance. Low-confidence fields can be filtered by threshold while still preserving higher-confidence facts from the same document.

### Query Design Tips
- Be specific about time boundaries: ask for "fiscal year 2023" instead of "last year".
- Include company names explicitly, especially for cross-document questions.
- Add file-type hints for non-PDF sources, such as "in the email" or "in the Excel sheet".
- For ratios like "as a percentage of," first ask for the raw numerator and denominator values if they are not already co-located.
- Avoid prompts that require multi-step arithmetic not present in source text (for example CAGR); request the raw figures first.
- Broad comparisons across many filings can miss lower-ranked chunks; narrow to two or three companies for higher precision.
- Ask for source-backed outputs explicitly (for example: "cite the filing name") to improve auditability.

### Edge Cases Handled
| Edge Case | How It Is Handled | File |
|---|---|---|
| Scanned PDF (no text layer) | pdfplumber returns empty string; parser falls back to PyMuPDF OCR path | parse/pdf.py |
| Excel with merged header cells | openpyxl returns None past first cell; parser forward-fills the value rightward | parse/excel.py |
| Excel with blank rows | Rows where all values are None are dropped before chunking | parse/excel.py |
| Oversized chunk (>8 000 tokens) | Recursive bisection in _split_long_text() until each piece fits | chunk.py |
| PDF with no detectable sections (<3 headings) | Falls back to 500-word sliding window with 50-word overlap | chunk.py |
| Embedding cache hit | SHA-256 keyed disk cache checked before every OpenAI call; hit skips API | cache.py |
| Email thread with multiple From: boundaries | Body split per boundary into separate chunks so replies are individually retrievable | chunk.py |
| Empty email body | chunk_email() checks for skipped flag and empty body; returns [] with no chunks created | chunk.py |
