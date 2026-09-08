-- P1-6: Durable mission execution substrate.
-- Makes AI Employee DURABLE, RECOVERABLE, IDEMPOTENT.
-- Database becomes source of truth for all execution state.
--
-- Architecture:
--   mission (existing root)
--     └── mission_execution (NEW: durable runtime/session state)
--           └── mission_steps (EXTENDED: durable planned work + step lifecycle)
--
-- This migration is additive only. It does not modify or drop existing tables,
-- columns, policies, or grants. It does not touch any P1-4 security migration.
-- All new root-owned resources preserve the existing ownership/RLS architecture.

BEGIN;

-- ============================================================================
-- 1. EXTEND mission_steps WITH EXECUTION TRACKING
-- ============================================================================

ALTER TABLE public.mission_steps
    ADD COLUMN IF NOT EXISTS execution_id UUID,
    ADD COLUMN IF NOT EXISTS attempt_index INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS result JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS retry_category TEXT
        CHECK (retry_category IN ('TRANSIENT', 'VALIDATION', 'AUTHORIZATION', 'APPROVAL', 'MISSING_INPUT', 'TOOL_NOT_FOUND', 'EXECUTION', 'PERMANENT'));

-- Indexes for execution tracking
CREATE INDEX IF NOT EXISTS idx_mission_steps_execution_id ON public.mission_steps (execution_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_steps_idempotency_key ON public.mission_steps (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_mission_steps_attempt_index ON public.mission_steps (execution_id, attempt_index);

-- ============================================================================
-- 2. CREATE mission_executions TABLE (durable runtime/session state)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.mission_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID NOT NULL REFERENCES public.missions(id) ON DELETE CASCADE,
    execution_id UUID NOT NULL UNIQUE,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'WAITING_APPROVAL', 'WAITING_INPUT', 'SUCCEEDED', 'FAILED', 'RETRYING', 'CANCELLED')),
    current_step_index INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    result JSONB DEFAULT '{}'::jsonb,
    owner_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL
);

COMMENT ON TABLE public.mission_executions IS 'Durable runtime/session state for executing a mission. Source of truth for execution lifecycle.';
COMMENT ON COLUMN public.mission_executions.mission_id IS 'Parent mission identifier.';
COMMENT ON COLUMN public.mission_executions.execution_id IS 'Unique execution session identifier (UUID).';
COMMENT ON COLUMN public.mission_executions.idempotency_key IS 'Deterministic key preventing duplicate execution creation from HTTP retry.';
COMMENT ON COLUMN public.mission_executions.status IS 'Execution lifecycle status: PENDING → RUNNING → WAITING_APPROVAL/WAITING_INPUT → SUCCEEDED/FAILED/RETRYING → terminal.';
COMMENT ON COLUMN public.mission_executions.current_step_index IS 'Index of the next step to execute in mission_steps.';
COMMENT ON COLUMN public.mission_executions.retry_count IS 'Total retry attempts across all steps in this execution.';
COMMENT ON COLUMN public.mission_executions.result IS 'Final execution result payload.';
COMMENT ON COLUMN public.mission_executions.owner_id IS 'Canonical owner (auth.users.id). RLS enforces isolation.';
COMMENT ON COLUMN public.mission_executions.started_at IS 'When execution transitioned to RUNNING.';
COMMENT ON COLUMN public.mission_executions.completed_at IS 'When execution reached terminal state.';

-- ============================================================================
-- 3. INDEXES FOR mission_executions
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_mission_executions_mission_id ON public.mission_executions (mission_id);
CREATE INDEX IF NOT EXISTS idx_mission_executions_execution_id ON public.mission_executions (execution_id);
CREATE INDEX IF NOT EXISTS idx_mission_executions_idempotency_key ON public.mission_executions (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_mission_executions_owner_id ON public.mission_executions (owner_id);
CREATE INDEX IF NOT EXISTS idx_mission_executions_status ON public.mission_executions (status);
CREATE INDEX IF NOT EXISTS idx_mission_executions_created_at_desc ON public.mission_executions (created_at DESC);

-- ============================================================================
-- 4. ENABLE RLS ON mission_executions
-- ============================================================================

ALTER TABLE public.mission_executions ENABLE ROW LEVEL SECURITY;

-- mission_executions: root resource, owner-scoped via owner_id = auth.uid()
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'mission_executions'
          AND policyname = 'mission_executions_select_own'
    ) THEN
        CREATE POLICY mission_executions_select_own ON public.mission_executions FOR SELECT
            USING (owner_id = auth.uid());
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'mission_executions'
          AND policyname = 'mission_executions_insert_own'
    ) THEN
        CREATE POLICY mission_executions_insert_own ON public.mission_executions FOR INSERT
            WITH CHECK (owner_id = auth.uid());
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'mission_executions'
          AND policyname = 'mission_executions_update_own'
    ) THEN
        CREATE POLICY mission_executions_update_own ON public.mission_executions FOR UPDATE
            USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'mission_executions'
          AND policyname = 'mission_executions_delete_own'
    ) THEN
        CREATE POLICY mission_executions_delete_own ON public.mission_executions FOR DELETE
            USING (owner_id = auth.uid());
    END IF;
END
$$;

-- mission_steps: already RLS-enabled via parent mission (sprint7_2g).
-- The existing policies use EXISTS (SELECT 1 FROM public.missions WHERE missions.id = mission_steps.mission_id AND missions.owner_id = auth.uid()).
-- No changes needed — relationship-based ownership is correct.

-- ============================================================================
-- 5. GRANTS
-- ============================================================================

REVOKE ALL ON public.mission_executions FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.mission_executions TO authenticated;
-- mission_steps already granted to authenticated (sprint7_2g)

-- ============================================================================
-- 6. FUNCTION: claim_mission_execution
-- ============================================================================
-- Atomic claim-or-create for mission execution with idempotency.
-- Uses INSERT ... EXCEPTION pattern (race-safe, like claim_onboarding_workflow_for_approval).
-- SECURITY INVOKER: auth.uid() evaluates to the authenticated caller.
-- The backend uses anon key by default; authenticated is retained for JWT requests.

CREATE OR REPLACE FUNCTION public.claim_mission_execution(
    p_mission_id UUID,
    p_execution_id UUID,
    p_idempotency_key TEXT,
    p_status TEXT DEFAULT 'PENDING'
) RETURNS TABLE (execution JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_existing public.mission_executions%ROWTYPE;
    v_inserted public.mission_executions%ROWTYPE;
BEGIN
    -- Attempt the insert. The unique idempotency_key is the final correctness
    -- backstop: at most one row can ever exist for a given idempotency key.
    INSERT INTO public.mission_executions (
        id, mission_id, execution_id, idempotency_key, status,
        current_step_index, retry_count, result, owner_id,
        created_at, updated_at
    ) VALUES (
        gen_random_uuid(), p_mission_id, p_execution_id, p_idempotency_key, p_status,
        0, 0, '{}'::jsonb, auth.uid(), now(), now()
    )
    RETURNING * INTO v_inserted;

    RETURN QUERY SELECT to_jsonb(v_inserted), true;
    RETURN;
EXCEPTION
    WHEN unique_violation THEN
        -- A concurrent caller inserted a row for this idempotency_key
        -- between any prior read and our INSERT. The unique index
        -- idx_mission_executions_idempotency_key rejected our duplicate.
        -- Return the existing execution so both callers see the same execution_id.
        SELECT * INTO v_existing
            FROM public.mission_executions
            WHERE idempotency_key = p_idempotency_key
            LIMIT 1;
        IF NOT FOUND THEN
            -- The unique violation was on a different constraint (e.g., PK collision on id).
            -- Re-raise so the caller can surface a real error.
            RAISE;
        END IF;
        RETURN QUERY SELECT to_jsonb(v_existing), false;
        RETURN;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_mission_execution(
    UUID, UUID, TEXT, TEXT
) TO authenticated;

-- ============================================================================
-- 7. FUNCTION: claim_mission_step
-- ============================================================================
-- Atomic claim of a step for execution with attempt isolation.
-- Ensures the same step attempt cannot be claimed twice concurrently.
-- Uses the mission_steps idempotency_key for uniqueness.

CREATE OR REPLACE FUNCTION public.claim_mission_step(
    p_execution_id UUID,
    p_step_id UUID,
    p_attempt_index INTEGER,
    p_idempotency_key TEXT
) RETURNS TABLE (step JSONB, claimed BOOLEAN)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_existing public.mission_steps%ROWTYPE;
    v_inserted public.mission_steps%ROWTYPE;
    v_mission_id UUID;
BEGIN
    -- Verify the execution exists and get owner for RLS.
    SELECT mission_id INTO v_mission_id
        FROM public.mission_executions
        WHERE id = p_execution_id;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::jsonb, false;
        RETURN;
    END IF;

    -- Attempt insert of the step attempt. The unique idempotency_key
    -- prevents duplicate side effects from HTTP retry of the same attempt.
    INSERT INTO public.mission_steps (
        mission_id, execution_id, step_name, worker_role, status,
        attempt_index, idempotency_key, started_at, completed_at, result, retry_category, created_at
    ) VALUES (
        v_mission_id, p_execution_id, 'claimed_step', 'employee', 'in_progress',
        p_attempt_index, p_idempotency_key, now(), NULL, '{}'::jsonb, NULL, now()
    )
    RETURNING * INTO v_inserted;

    RETURN QUERY SELECT to_jsonb(v_inserted), true;
    RETURN;
EXCEPTION
    WHEN unique_violation THEN
        -- A concurrent caller claimed this same step attempt.
        -- Return the existing step so both callers see the same state.
        SELECT * INTO v_existing
            FROM public.mission_steps
            WHERE idempotency_key = p_idempotency_key
            LIMIT 1;
        IF NOT FOUND THEN
            RAISE;
        END IF;
        RETURN QUERY SELECT to_jsonb(v_existing), false;
        RETURN;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_mission_step(
    UUID, UUID, INTEGER, TEXT
) TO authenticated;

-- ============================================================================
-- 8. FUNCTION: update_execution_state
-- ============================================================================
-- Atomic update of execution state with ownership check.
-- Returns the updated row or NULL if the execution doesn't exist or owner mismatch.

CREATE OR REPLACE FUNCTION public.update_execution_state(
    p_execution_id UUID,
    p_status TEXT DEFAULT NULL,
    p_current_step_index INTEGER DEFAULT NULL,
    p_retry_count INTEGER DEFAULT NULL,
    p_result JSONB DEFAULT NULL,
    p_completed_at TIMESTAMPTZ DEFAULT NULL
) RETURNS TABLE (execution JSONB)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_updated public.mission_executions%ROWTYPE;
BEGIN
    UPDATE public.mission_executions
    SET
        status = COALESCE(p_status, status),
        current_step_index = COALESCE(p_current_step_index, current_step_index),
        retry_count = COALESCE(p_retry_count, retry_count),
        result = COALESCE(p_result, result),
        completed_at = COALESCE(p_completed_at, completed_at),
        updated_at = now()
    WHERE id = p_execution_id
        AND owner_id = auth.uid()
    RETURNING * INTO v_updated;

    IF v_updated IS NULL THEN
        RETURN QUERY SELECT NULL::jsonb;
        RETURN;
    END IF;

    RETURN QUERY SELECT to_jsonb(v_updated);
END;
$$;

GRANT EXECUTE ON FUNCTION public.update_execution_state(
    UUID, TEXT, INTEGER, INTEGER, JSONB, TIMESTAMPTZ
) TO authenticated;

-- ============================================================================
-- 9. FUNCTION: complete_execution
-- ============================================================================
-- Atomically mark execution as succeeded or failed with final result.
-- Only allows terminal transitions from non-terminal states.

CREATE OR REPLACE FUNCTION public.complete_execution(
    p_execution_id UUID,
    p_status TEXT,
    p_result JSONB DEFAULT NULL
) RETURNS TABLE (execution JSONB)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_updated public.mission_executions%ROWTYPE;
    v_current_status TEXT;
BEGIN
    -- Verify ownership and get current status
    SELECT status INTO v_current_status
        FROM public.mission_executions
        WHERE id = p_execution_id AND owner_id = auth.uid();

    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::jsonb;
        RETURN;
    END IF;

    -- Only allow transition from non-terminal states
    IF v_current_status IN ('SUCCEEDED', 'FAILED', 'CANCELLED') THEN
        RETURN QUERY SELECT NULL::jsonb;
        RETURN;
    END IF;

    -- Validate terminal status
    IF p_status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') THEN
        RETURN QUERY SELECT NULL::jsonb;
        RETURN;
    END IF;

    UPDATE public.mission_executions
    SET
        status = p_status,
        result = COALESCE(p_result, '{}'::jsonb),
        completed_at = now(),
        updated_at = now()
    WHERE id = p_execution_id
    RETURNING * INTO v_updated;

    RETURN QUERY SELECT to_jsonb(v_updated);
END;
$$;

GRANT EXECUTE ON FUNCTION public.complete_execution(
    UUID, TEXT, JSONB
) TO authenticated;

COMMIT;