"""Database schema for session state.

Postgres tables: threads, messages, runs, feedback.
All async, with proper indexes and JSONB for metadata.
"""

from __future__ import annotations

# Schema name owned by the app's SP. Databricks Apps grants the SP
# CAN_CONNECT_AND_CREATE on the Lakebase database, which translates to
# CONNECT + CREATE on the DATABASE, but NOT CREATE on the default
# `public` schema (Postgres 15+ revokes public CREATE). So we create
# our own schema, own it, and put all session tables there.
COCO_APP_SCHEMA = "coco_sessions"

# Shorthand for fully-qualified table names. Every CREATE TABLE,
# CREATE INDEX, and REFERENCES clause uses this prefix so the DDL
# works regardless of search_path settings (which proved unreliable
# in multi-statement batch execute on psycopg3 + Lakebase).
_S = COCO_APP_SCHEMA

SCHEMA_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {_S};

CREATE TABLE IF NOT EXISTS {_S}.threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    title VARCHAR(1024),
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_threads_user_updated
ON {_S}.threads(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS {_S}.messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES {_S}.threads(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    tool_calls JSONB,
    trace_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_thread_created
ON {_S}.messages(thread_id, created_at);

CREATE TABLE IF NOT EXISTS {_S}.runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES {_S}.threads(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES {_S}.messages(id) ON DELETE CASCADE,
    statement_id VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    error TEXT,
    result_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_statement_id
ON {_S}.runs(statement_id) WHERE statement_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_runs_thread_id
ON {_S}.runs(thread_id);

CREATE TABLE IF NOT EXISTS {_S}.feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES {_S}.messages(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    rating INT NOT NULL,
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_message_id
ON {_S}.feedback(message_id);

CREATE INDEX IF NOT EXISTS idx_feedback_user_id
ON {_S}.feedback(user_id);

-- One row per (message, user). Second click from the same user on
-- the same message upserts the rating instead of appending a duplicate,
-- which would double-count in the optimizer's training set.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'feedback_message_user_unique'
    ) THEN
        -- Collapse any existing duplicates before adding the constraint.
        DELETE FROM {_S}.feedback a
        USING {_S}.feedback b
        WHERE a.ctid < b.ctid
          AND a.message_id = b.message_id
          AND a.user_id = b.user_id;
        ALTER TABLE {_S}.feedback
            ADD CONSTRAINT feedback_message_user_unique
            UNIQUE (message_id, user_id);
    END IF;
END$$;

-- Backfill updated_at on existing rows that predate the new column.
ALTER TABLE {_S}.feedback
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE
        NOT NULL DEFAULT NOW();
"""
