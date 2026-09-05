-- Sprint 3: Create a dedicated worker registry table for storing worker metadata.
-- This migration adds a new table only and leaves existing tables unchanged.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS worker_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    worker_type TEXT NOT NULL,
    platform TEXT,
    status TEXT DEFAULT 'offline',
    capabilities JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT now()
);
