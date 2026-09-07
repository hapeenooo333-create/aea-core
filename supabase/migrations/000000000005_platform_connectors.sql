-- Sprint 7.2-B: Add platform connector persistence tables.
-- This migration creates tables for managing platform connections, onboarding workflows,
-- and human intervention checkpoints. All migrations are additive only.

BEGIN;

-- Table for tracking platform account connections
CREATE TABLE IF NOT EXISTS public.platform_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_account_id TEXT,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'not_started',
    scopes TEXT[],
    token_reference TEXT,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.platform_connections IS 'Stores platform account connections with status tracking. Tokens are never stored directly; only secure references.';
COMMENT ON COLUMN public.platform_connections.owner_id IS 'Identifier of the worker/owner of this connection.';
COMMENT ON COLUMN public.platform_connections.platform IS 'Platform name (e.g., pinterest, youtube).';
COMMENT ON COLUMN public.platform_connections.external_account_id IS 'External account ID on the platform.';
COMMENT ON COLUMN public.platform_connections.status IS 'Connection status (not_started, onboarding, connected, needs_reconnect, failed).';
COMMENT ON COLUMN public.platform_connections.token_reference IS 'Secure reference to stored credentials (never raw token).';

CREATE INDEX IF NOT EXISTS idx_platform_connections_owner_id
    ON public.platform_connections (owner_id);

CREATE INDEX IF NOT EXISTS idx_platform_connections_platform
    ON public.platform_connections (platform);

CREATE INDEX IF NOT EXISTS idx_platform_connections_status
    ON public.platform_connections (status);

-- Table for tracking onboarding workflows
CREATE TABLE IF NOT EXISTS public.onboarding_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER DEFAULT 1,
    total_steps INTEGER DEFAULT 1,
    checkpoint_data JSONB DEFAULT '{}'::jsonb,
    step_history JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.onboarding_workflows IS 'Tracks the lifecycle of platform onboarding workflows with step progression.';
COMMENT ON COLUMN public.onboarding_workflows.mission_id IS 'Associated mission identifier.';
COMMENT ON COLUMN public.onboarding_workflows.worker_id IS 'Worker performing the onboarding.';
COMMENT ON COLUMN public.onboarding_workflows.platform IS 'Platform being onboarded (e.g., pinterest).';
COMMENT ON COLUMN public.onboarding_workflows.current_step IS 'Current step in the workflow.';
COMMENT ON COLUMN public.onboarding_workflows.checkpoint_data IS 'Data from the current checkpoint (non-sensitive).';
COMMENT ON COLUMN public.onboarding_workflows.step_history IS 'Historical record of all steps and their status.';

CREATE INDEX IF NOT EXISTS idx_onboarding_workflows_mission_id
    ON public.onboarding_workflows (mission_id);

CREATE INDEX IF NOT EXISTS idx_onboarding_workflows_worker_id
    ON public.onboarding_workflows (worker_id);

CREATE INDEX IF NOT EXISTS idx_onboarding_workflows_platform
    ON public.onboarding_workflows (platform);

CREATE INDEX IF NOT EXISTS idx_onboarding_workflows_status
    ON public.onboarding_workflows (status);

-- Table for human intervention checkpoints
CREATE TABLE IF NOT EXISTS public.human_intervention_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_human',
    instructions TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    expires_at TIMESTAMPTZ NULL
);

COMMENT ON TABLE public.human_intervention_checkpoints IS 'Tracks human intervention checkpoints for platform workflows (OTP, OAuth, email verification, etc.).';
COMMENT ON COLUMN public.human_intervention_checkpoints.mission_id IS 'Associated mission identifier.';
COMMENT ON COLUMN public.human_intervention_checkpoints.platform IS 'Platform this checkpoint is for.';
COMMENT ON COLUMN public.human_intervention_checkpoints.checkpoint_type IS 'Type of checkpoint (otp_required, oauth_authorization_required, email_verification_required, etc.).';
COMMENT ON COLUMN public.human_intervention_checkpoints.status IS 'Checkpoint status (awaiting_human, completed, failed, expired).';
COMMENT ON COLUMN public.human_intervention_checkpoints.instructions IS 'Human-readable instructions for completing the checkpoint.';
COMMENT ON COLUMN public.human_intervention_checkpoints.metadata IS 'Additional context and data for the checkpoint (non-sensitive).';

CREATE INDEX IF NOT EXISTS idx_human_intervention_checkpoints_mission_id
    ON public.human_intervention_checkpoints (mission_id);

CREATE INDEX IF NOT EXISTS idx_human_intervention_checkpoints_platform
    ON public.human_intervention_checkpoints (platform);

CREATE INDEX IF NOT EXISTS idx_human_intervention_checkpoints_status
    ON public.human_intervention_checkpoints (status);

CREATE INDEX IF NOT EXISTS idx_human_intervention_checkpoints_created_at_desc
    ON public.human_intervention_checkpoints (created_at DESC);

-- Enable RLS for all new tables
ALTER TABLE public.platform_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.onboarding_workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.human_intervention_checkpoints ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for platform_connections
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'platform_connections'
          AND policyname = 'platform_connections_select_all_rows'
    ) THEN
        CREATE POLICY platform_connections_select_all_rows
            ON public.platform_connections
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
          AND tablename = 'platform_connections'
          AND policyname = 'platform_connections_insert_rows'
    ) THEN
        CREATE POLICY platform_connections_insert_rows
            ON public.platform_connections
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
          AND tablename = 'platform_connections'
          AND policyname = 'platform_connections_update_rows'
    ) THEN
        CREATE POLICY platform_connections_update_rows
            ON public.platform_connections
            FOR UPDATE
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

-- Create RLS policies for onboarding_workflows
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'onboarding_workflows'
          AND policyname = 'onboarding_workflows_select_all_rows'
    ) THEN
        CREATE POLICY onboarding_workflows_select_all_rows
            ON public.onboarding_workflows
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
          AND tablename = 'onboarding_workflows'
          AND policyname = 'onboarding_workflows_insert_rows'
    ) THEN
        CREATE POLICY onboarding_workflows_insert_rows
            ON public.onboarding_workflows
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
          AND tablename = 'onboarding_workflows'
          AND policyname = 'onboarding_workflows_update_rows'
    ) THEN
        CREATE POLICY onboarding_workflows_update_rows
            ON public.onboarding_workflows
            FOR UPDATE
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

-- Create RLS policies for human_intervention_checkpoints
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'human_intervention_checkpoints'
          AND policyname = 'human_intervention_checkpoints_select_all_rows'
    ) THEN
        CREATE POLICY human_intervention_checkpoints_select_all_rows
            ON public.human_intervention_checkpoints
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
          AND tablename = 'human_intervention_checkpoints'
          AND policyname = 'human_intervention_checkpoints_insert_rows'
    ) THEN
        CREATE POLICY human_intervention_checkpoints_insert_rows
            ON public.human_intervention_checkpoints
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
          AND tablename = 'human_intervention_checkpoints'
          AND policyname = 'human_intervention_checkpoints_update_rows'
    ) THEN
        CREATE POLICY human_intervention_checkpoints_update_rows
            ON public.human_intervention_checkpoints
            FOR UPDATE
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

COMMIT;
