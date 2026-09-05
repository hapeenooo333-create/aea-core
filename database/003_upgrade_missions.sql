BEGIN;

ALTER TABLE IF EXISTS missions
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS assigned_worker UUID,
    ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS result JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT now();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'missions'::regclass
          AND conname = 'missions_progress_check'
    ) THEN
        ALTER TABLE missions
            ADD CONSTRAINT missions_progress_check
            CHECK (progress >= 0 AND progress <= 100);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'missions'
          AND c.conname = 'missions_assigned_worker_fkey'
    ) THEN
        ALTER TABLE missions
            ADD CONSTRAINT missions_assigned_worker_fkey
            FOREIGN KEY (assigned_worker)
            REFERENCES worker_registry(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
CREATE INDEX IF NOT EXISTS idx_missions_worker ON missions(assigned_worker);

COMMIT;
