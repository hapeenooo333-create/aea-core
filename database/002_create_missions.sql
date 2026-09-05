CREATE TABLE IF NOT EXISTS missions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    assigned_worker UUID REFERENCES worker_registry(id) ON DELETE SET NULL,
    priority TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    result JSONB DEFAULT '{}'::jsonb,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
