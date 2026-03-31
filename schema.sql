-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL CHECK (file_type IN ('pdf', 'excel', 'email', 'htm', 'unknown')),
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
