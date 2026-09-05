-- Sprint 7.2-A: Add approval request persistence for human approval workflows.
-- This migration creates a table for tracking approval requests for sensitive actions.
-- The table supports storing approval state changes and includes defensive defaults.
-- This migration is additive only and does not modify or drop existing tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NULL,
    approved_at TIMESTAMPTZ NULL,
    rejected_at TIMESTAMPTZ NULL,
    approved_by TEXT NULL,
    rejected_by TEXT NULL,
    reason TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.approval_requests IS 'Stores approval requests for sensitive actions that require human review before execution.';
COMMENT ON COLUMN public.approval_requests.id IS 'Unique identifier for the approval request.';
COMMENT ON COLUMN public.approval_requests.mission_id IS 'Identifier of the associated mission (TEXT for compatibility with missions table).';
COMMENT ON COLUMN public.approval_requests.action_type IS 'Type of action requiring approval (e.g., publish_content, create_account).';
COMMENT ON COLUMN public.approval_requests.risk_level IS 'Risk classification of the action (safe, moderate, sensitive).';
COMMENT ON COLUMN public.approval_requests.status IS 'Current approval state (pending, approved, rejected, expired).';
COMMENT ON COLUMN public.approval_requests.requested_at IS 'Timestamp when the approval request was created.';
COMMENT ON COLUMN public.approval_requests.expires_at IS 'Timestamp when the approval request expires (optional).';
COMMENT ON COLUMN public.approval_requests.approved_at IS 'Timestamp when the request was approved (null if not approved).';
COMMENT ON COLUMN public.approval_requests.rejected_at IS 'Timestamp when the request was rejected (null if not rejected).';
COMMENT ON COLUMN public.approval_requests.approved_by IS 'Identifier of the user who approved the request (null if not approved).';
COMMENT ON COLUMN public.approval_requests.rejected_by IS 'Identifier of the user who rejected the request (null if not rejected).';
COMMENT ON COLUMN public.approval_requests.reason IS 'Reason for rejection (null if not rejected).';
COMMENT ON COLUMN public.approval_requests.metadata IS 'JSON metadata containing action-specific payload and context.';
COMMENT ON COLUMN public.approval_requests.created_at IS 'Timestamp when the record was created in the database.';
COMMENT ON COLUMN public.approval_requests.updated_at IS 'Timestamp when the record was last updated in the database.';

CREATE INDEX IF NOT EXISTS idx_approval_requests_mission_id
    ON public.approval_requests (mission_id);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status
    ON public.approval_requests (status);

CREATE INDEX IF NOT EXISTS idx_approval_requests_requested_at_desc
    ON public.approval_requests (requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_approval_requests_expires_at
    ON public.approval_requests (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at_desc
    ON public.approval_requests (created_at DESC);

ALTER TABLE public.approval_requests ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'approval_requests'
          AND policyname = 'approval_requests_select_all_rows'
    ) THEN
        CREATE POLICY approval_requests_select_all_rows
            ON public.approval_requests
            FOR SELECT
            USING (true);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'approval_requests'
          AND policyname = 'approval_requests_insert_rows'
    ) THEN
        CREATE POLICY approval_requests_insert_rows
            ON public.approval_requests
            FOR INSERT
            WITH CHECK (true);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'approval_requests'
          AND policyname = 'approval_requests_update_rows'
    ) THEN
        CREATE POLICY approval_requests_update_rows
            ON public.approval_requests
            FOR UPDATE
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

COMMIT;
