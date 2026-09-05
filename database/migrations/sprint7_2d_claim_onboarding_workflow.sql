-- Sprint 7.2-C (P1-3): Atomic claim-or-create for an onboarding workflow
-- tied to a specific approval_id.
--
-- This function is the database-authoritative idempotency primitive for
-- the start_onboarding flow. It is concurrency-safe under concurrent
-- invocations because it uses SELECT ... FOR UPDATE on the candidate
-- row inside a single transaction.
--
-- The function is plain SECURITY INVOKER. RLS on
-- public.onboarding_workflows is enabled with permissive policies
-- (USING true / WITH CHECK true) so the invoking role (anon or
-- authenticated) is sufficient.
--
-- Returns a JSON object with two fields:
--   workflow: the row as jsonb (the existing or newly created workflow)
--   created:  boolean true if this call inserted, false if it returned
--             an existing row.
--
-- Schema-qualified names are used throughout to avoid search_path
-- surprises.
BEGIN;

CREATE OR REPLACE FUNCTION public.claim_onboarding_workflow_for_approval(
    p_approval_id UUID,
    p_workflow_id UUID,
    p_mission_id TEXT,
    p_worker_id TEXT,
    p_platform TEXT,
    p_status TEXT,
    p_current_step INTEGER,
    p_total_steps INTEGER,
    p_checkpoint_data JSONB,
    p_step_history JSONB
) RETURNS TABLE (workflow JSONB, created BOOLEAN)
LANGUAGE plpgsql
AS $$
DECLARE
    v_existing public.onboarding_workflows%ROWTYPE;
    v_inserted public.onboarding_workflows%ROWTYPE;
BEGIN
    -- Look up an existing workflow for this approval. The partial unique
    -- index on started_by_approval_id ensures at most one row matches.
    -- FOR UPDATE locks the candidate so a concurrent caller waits until
    -- this transaction commits before reading.
    SELECT * INTO v_existing
        FROM public.onboarding_workflows
        WHERE started_by_approval_id = p_approval_id
        LIMIT 1
        FOR UPDATE;

    IF FOUND THEN
        RETURN QUERY SELECT to_jsonb(v_existing), false;
        RETURN;
    END IF;

    -- No existing row; create one. The partial unique index is the final
    -- backstop: if a concurrent insert slipped in between our SELECT and
    -- INSERT, the index will reject the duplicate with unique_violation
    -- and the caller will see an exception that the store handles.
    INSERT INTO public.onboarding_workflows (
        id,
        mission_id,
        worker_id,
        platform,
        status,
        current_step,
        total_steps,
        checkpoint_data,
        step_history,
        started_by_approval_id,
        created_at,
        updated_at
    ) VALUES (
        p_workflow_id,
        p_mission_id,
        p_worker_id,
        p_platform,
        p_status,
        p_current_step,
        p_total_steps,
        COALESCE(p_checkpoint_data, '{}'::jsonb),
        COALESCE(p_step_history, '[]'::jsonb),
        p_approval_id,
        now(),
        now()
    )
    RETURNING * INTO v_inserted;

    RETURN QUERY SELECT to_jsonb(v_inserted), true;
END;
$$;

-- Grant execute to standard Supabase client roles. The application
-- uses anon-key by default; service_role is also allowed for tests
-- and admin operations.
GRANT EXECUTE ON FUNCTION public.claim_onboarding_workflow_for_approval(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, JSONB, JSONB
) TO anon, authenticated, service_role;

COMMIT;
