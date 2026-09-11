-- P1-7D: concurrency-safe claims and stable connector operation identity.
BEGIN;

ALTER TABLE public.mission_steps
    ADD COLUMN IF NOT EXISTS operation_key TEXT,
    ADD COLUMN IF NOT EXISTS claim_token TEXT,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_mission_steps_operation_key
    ON public.mission_steps (execution_id, operation_key);
CREATE INDEX IF NOT EXISTS idx_mission_steps_lease
    ON public.mission_steps (lease_expires_at)
    WHERE status = 'in_progress';

COMMENT ON COLUMN public.mission_steps.operation_key IS
    'Server-derived identity of one logical side effect; shared by all retry attempts.';
COMMENT ON COLUMN public.mission_steps.claim_token IS
    'Worker fencing token. Only the current lease holder may complete a claimed step.';
COMMENT ON COLUMN public.mission_steps.lease_expires_at IS
    'Time after which an in-progress claim may be recovered by another worker.';

CREATE OR REPLACE FUNCTION public.claim_mission_step(
    p_execution_id UUID,
    p_step_id UUID,
    p_attempt_index INTEGER,
    p_idempotency_key TEXT,
    p_operation_key TEXT,
    p_claim_token TEXT,
    p_lease_seconds INTEGER DEFAULT 60
) RETURNS TABLE (step JSONB, claimed BOOLEAN)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_existing public.mission_steps%ROWTYPE;
    v_latest public.mission_steps%ROWTYPE;
    v_inserted public.mission_steps%ROWTYPE;
    v_mission_id UUID;
    v_operation_key TEXT := COALESCE(p_operation_key, p_idempotency_key);
BEGIN
    SELECT mission_id INTO v_mission_id
    FROM public.mission_executions
    WHERE id = p_execution_id;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::jsonb, false;
        RETURN;
    END IF;

    SELECT * INTO v_existing
    FROM public.mission_steps
    WHERE execution_id = p_execution_id AND idempotency_key = p_idempotency_key
    LIMIT 1;
    IF FOUND THEN
        RETURN QUERY SELECT to_jsonb(v_existing), false;
        RETURN;
    END IF;

    SELECT * INTO v_latest
    FROM public.mission_steps
    WHERE execution_id = p_execution_id
      AND operation_key = v_operation_key
    ORDER BY attempt_index DESC, created_at DESC
    LIMIT 1
    FOR UPDATE;
    IF FOUND THEN
        IF v_latest.status = 'completed' THEN
            RETURN QUERY SELECT to_jsonb(v_latest), false;
            RETURN;
        END IF;
        IF v_latest.status = 'in_progress'
           AND v_latest.lease_expires_at IS NOT NULL
           AND v_latest.lease_expires_at > now() THEN
            RETURN QUERY SELECT to_jsonb(v_latest), false;
            RETURN;
        END IF;
        IF v_latest.status = 'in_progress' THEN
            UPDATE public.mission_steps
            SET status = 'failed',
                retry_category = 'EXECUTION',
                claim_token = NULL,
                result = jsonb_build_object('recovered', 'stale_claim'),
                completed_at = now()
            WHERE id = v_latest.id;
        END IF;
    END IF;

    INSERT INTO public.mission_steps (
        mission_id, execution_id, step_name, worker_role, status,
        attempt_index, idempotency_key, operation_key, claim_token,
        lease_expires_at, started_at, completed_at, result, retry_category, created_at
    ) VALUES (
        v_mission_id, p_execution_id, 'claimed_step', 'employee', 'in_progress',
        p_attempt_index, p_idempotency_key, v_operation_key, p_claim_token,
        now() + make_interval(secs => GREATEST(p_lease_seconds, 1)),
        now(), NULL, '{}'::jsonb, NULL, now()
    )
    RETURNING * INTO v_inserted;

    RETURN QUERY SELECT to_jsonb(v_inserted), true;
EXCEPTION
    WHEN unique_violation THEN
        SELECT * INTO v_existing
        FROM public.mission_steps
        WHERE execution_id = p_execution_id AND idempotency_key = p_idempotency_key
        LIMIT 1;
        IF FOUND THEN
            RETURN QUERY SELECT to_jsonb(v_existing), false;
            RETURN;
        END IF;
        RAISE;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_mission_step(UUID, UUID, INTEGER, TEXT, TEXT, TEXT, INTEGER)
    TO authenticated;
REVOKE ALL ON FUNCTION public.claim_mission_step(UUID, UUID, INTEGER, TEXT, TEXT, TEXT, INTEGER)
    FROM anon;

COMMIT;
