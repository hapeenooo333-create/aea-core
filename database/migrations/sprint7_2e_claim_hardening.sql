-- Sprint 7.2-C (P1-3 hardening): Race-free claim_onboarding_workflow_for_approval.
--
-- The previous version of this function used SELECT ... FOR UPDATE
-- followed by INSERT. That pattern is NOT safe for the
-- concurrent-first-creation case: FOR UPDATE cannot lock a row that
-- does not yet exist, so two simultaneous callers would both see "no
-- row" and both attempt INSERT, with one of them receiving 23505
-- unique_violation from the partial unique index.
--
-- This migration replaces the function with a hardened implementation
-- that wraps the INSERT in an EXCEPTION block. If a concurrent insert
-- wins the race, the loser catches 23505 and returns the existing row
-- instead of surfacing the error to the application.
--
-- The function remains SECURITY INVOKER. RLS on
-- public.onboarding_workflows is permissive (USING true / WITH CHECK
-- true) so the invoking role is sufficient.
--
-- Grants are narrowed: the backend uses the anon key (SUPABASE_KEY /
-- SUPABASE_ANON_KEY) and never the service_role key. service_role
-- was previously granted but is not actually used by the application;
-- it is removed to follow least-privilege. authenticated is retained
-- because the Supabase client can issue requests as an authenticated
-- user when a JWT is supplied.
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
    -- Attempt the insert. The partial unique index on
    -- started_by_approval_id is the final correctness backstop: at most
    -- one row can ever exist for a given non-null approval_id.
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
    RETURN;
EXCEPTION
    WHEN unique_violation THEN
        -- A concurrent caller inserted a row for this approval_id
        -- between any prior read and our INSERT. The partial unique
        -- index ux_onboarding_workflows_started_by_approval_id
        -- rejected our duplicate. Return the row that won the race
        -- so both callers see the same workflow_id.
        SELECT * INTO v_existing
            FROM public.onboarding_workflows
            WHERE started_by_approval_id = p_approval_id
            LIMIT 1;
        IF NOT FOUND THEN
            -- The unique violation was on a different constraint
            -- (e.g., PK collision on id). Re-raise so the caller
            -- can surface a real error.
            RAISE;
        END IF;
        RETURN QUERY SELECT to_jsonb(v_existing), false;
        RETURN;
END;
$$;

-- Restrict grants to the roles the backend actually uses. The
-- application reads SUPABASE_KEY (anon-key) by default and may also
-- pass a user JWT (authenticated). service_role is not used and is
-- removed for least-privilege.
REVOKE ALL ON FUNCTION public.claim_onboarding_workflow_for_approval(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, JSONB, JSONB
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.claim_onboarding_workflow_for_approval(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, JSONB, JSONB
) TO anon, authenticated;

COMMIT;
