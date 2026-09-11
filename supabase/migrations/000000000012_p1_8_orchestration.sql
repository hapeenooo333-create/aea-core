-- P1-8: bounded employee orchestration for affiliate jobs.
BEGIN;

ALTER TABLE public.missions
    ADD COLUMN IF NOT EXISTS objective TEXT,
    ADD COLUMN IF NOT EXISTS urgency TEXT DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS business_importance INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS recurrence TEXT NULL,
    ADD COLUMN IF NOT EXISTS dependencies UUID[] DEFAULT '{}'::uuid[],
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS domain TEXT DEFAULT 'general';
ALTER TABLE public.missions
    ADD COLUMN IF NOT EXISTS orchestration_claim_token TEXT NULL,
    ADD COLUMN IF NOT EXISTS orchestration_lease_expires_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS orchestration_idempotency_key TEXT NULL;

ALTER TABLE public.missions DROP CONSTRAINT IF EXISTS missions_status_check;
ALTER TABLE public.missions ADD CONSTRAINT missions_status_check CHECK (
    status IS NULL OR status IN (
        'pending', 'scheduled', 'active', 'paused', 'retrying', 'waiting_dependency',
        'waiting_approval', 'waiting_human', 'completed', 'failed', 'cancelled'
    )
);
ALTER TABLE public.missions DROP CONSTRAINT IF EXISTS missions_business_importance_check;
ALTER TABLE public.missions ADD CONSTRAINT missions_business_importance_check
    CHECK (business_importance IS NULL OR business_importance BETWEEN 1 AND 5);

CREATE INDEX IF NOT EXISTS idx_missions_owner_status_schedule
    ON public.missions (owner_id, status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_missions_owner_priority
    ON public.missions (owner_id, priority, urgency, created_at);
CREATE INDEX IF NOT EXISTS idx_missions_orchestration_lease
    ON public.missions (orchestration_lease_expires_at)
    WHERE orchestration_claim_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_missions_owner_orchestration_idempotency
    ON public.missions (owner_id, orchestration_idempotency_key)
    WHERE orchestration_idempotency_key IS NOT NULL;

CREATE OR REPLACE FUNCTION public.claim_mission_for_orchestration(
    p_mission_id UUID,
    p_claim_token TEXT,
    p_lease_seconds INTEGER DEFAULT 60
) RETURNS TABLE (mission JSONB, claimed BOOLEAN)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_mission public.missions%ROWTYPE;
BEGIN
    SELECT * INTO v_mission FROM public.missions
    WHERE id = p_mission_id AND owner_id = auth.uid()
    FOR UPDATE;
    IF NOT FOUND OR v_mission.status IN ('completed', 'failed', 'cancelled') THEN
        RETURN QUERY SELECT NULL::jsonb, false;
        RETURN;
    END IF;
    IF v_mission.orchestration_claim_token IS NOT NULL
       AND v_mission.orchestration_lease_expires_at IS NOT NULL
       AND v_mission.orchestration_lease_expires_at > now() THEN
        RETURN QUERY SELECT to_jsonb(v_mission), false;
        RETURN;
    END IF;
    UPDATE public.missions
    SET orchestration_claim_token = p_claim_token,
        orchestration_lease_expires_at = now() + make_interval(secs => GREATEST(p_lease_seconds, 1)),
        updated_at = now()
    WHERE id = p_mission_id AND owner_id = auth.uid()
    RETURNING * INTO v_mission;
    RETURN QUERY SELECT to_jsonb(v_mission), true;
END;
$$;

GRANT EXECUTE ON FUNCTION public.claim_mission_for_orchestration(UUID, TEXT, INTEGER) TO authenticated;
REVOKE ALL ON FUNCTION public.claim_mission_for_orchestration(UUID, TEXT, INTEGER) FROM anon;

CREATE TABLE IF NOT EXISTS public.mission_orchestration_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    mission_id UUID NOT NULL REFERENCES public.missions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.mission_orchestration_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mission_orchestration_events_select_own ON public.mission_orchestration_events;
DROP POLICY IF EXISTS mission_orchestration_events_insert_own ON public.mission_orchestration_events;
DROP POLICY IF EXISTS mission_orchestration_events_delete_own ON public.mission_orchestration_events;
CREATE POLICY mission_orchestration_events_select_own ON public.mission_orchestration_events
    FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY mission_orchestration_events_insert_own ON public.mission_orchestration_events
    FOR INSERT WITH CHECK (
        owner_id = auth.uid() AND EXISTS (
            SELECT 1 FROM public.missions m
            WHERE m.id = mission_orchestration_events.mission_id AND m.owner_id = auth.uid()
        )
    );
CREATE POLICY mission_orchestration_events_delete_own ON public.mission_orchestration_events
    FOR DELETE USING (owner_id = auth.uid());

REVOKE ALL ON public.mission_orchestration_events FROM anon;
GRANT SELECT, INSERT, DELETE ON public.mission_orchestration_events TO authenticated;
CREATE INDEX IF NOT EXISTS idx_mission_orchestration_events_owner_created
    ON public.mission_orchestration_events (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mission_orchestration_events_mission_created
    ON public.mission_orchestration_events (mission_id, created_at DESC);

COMMIT;
