-- P1-4C: Row-Level Security Enforcement
--
-- Enforces the authorization boundary:
--   authenticated JWT -> auth.uid() -> owner_id -> RLS -> authorized rows only
--
-- Properties:
--   - additive where possible
--   - idempotent (IF NOT EXISTS / DROP POLICY IF EXISTS)
--   - non-destructive (no DELETE/DROP TABLE)
--   - safe for existing databases

BEGIN;

-- ============================================================================
-- 1. OWNERSHIP COLUMNS
-- ============================================================================

-- Root tables: add canonical owner_id columns
ALTER TABLE public.workers ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE public.missions ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE public.approval_requests ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE public.identity_vault ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE public.notifications ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE public.memory_entries ADD COLUMN IF NOT EXISTS owner_id UUID;

-- Canonical agent_memory_entries table (application already references this name)
CREATE TABLE IF NOT EXISTS public.agent_memory_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID,
    worker_id UUID,
    mission_id UUID,
    memory_type TEXT,
    content JSONB,
    metadata JSONB,
    importance_score FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Platform connections: canonical UUID owner column
ALTER TABLE public.platform_connections ADD COLUMN IF NOT EXISTS owner_id_uuid UUID;

-- Indexes for owner columns
CREATE INDEX IF NOT EXISTS idx_workers_owner_id ON public.workers (owner_id);
CREATE INDEX IF NOT EXISTS idx_missions_owner_id ON public.missions (owner_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_owner_id ON public.approval_requests (owner_id);
CREATE INDEX IF NOT EXISTS idx_identity_vault_owner_id ON public.identity_vault (owner_id);
CREATE INDEX IF NOT EXISTS idx_notifications_owner_id ON public.notifications (owner_id);
CREATE INDEX IF NOT EXISTS idx_memory_entries_owner_id ON public.memory_entries (owner_id);
CREATE INDEX IF NOT EXISTS idx_agent_memory_entries_owner_id ON public.agent_memory_entries (owner_id);
CREATE INDEX IF NOT EXISTS idx_platform_connections_owner_id_uuid ON public.platform_connections (owner_id_uuid);

-- ============================================================================
-- 2. ENABLE RLS ON ROOT TABLES
-- ============================================================================

ALTER TABLE public.workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.missions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.identity_vault ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_memory_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_connections ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 3. DROP LEGACY PERMISSIVE POLICIES
-- ============================================================================

-- approval_requests
DROP POLICY IF EXISTS approval_requests_select_all_rows ON public.approval_requests;
DROP POLICY IF EXISTS approval_requests_insert_rows ON public.approval_requests;
DROP POLICY IF EXISTS approval_requests_update_rows ON public.approval_requests;

-- platform_connections
DROP POLICY IF EXISTS platform_connections_select_all_rows ON public.platform_connections;
DROP POLICY IF EXISTS platform_connections_insert_rows ON public.platform_connections;
DROP POLICY IF EXISTS platform_connections_update_rows ON public.platform_connections;

-- onboarding_workflows
DROP POLICY IF EXISTS onboarding_workflows_select_all_rows ON public.onboarding_workflows;
DROP POLICY IF EXISTS onboarding_workflows_insert_rows ON public.onboarding_workflows;
DROP POLICY IF EXISTS onboarding_workflows_update_rows ON public.onboarding_workflows;

-- human_intervention_checkpoints
DROP POLICY IF EXISTS human_intervention_checkpoints_select_all_rows ON public.human_intervention_checkpoints;
DROP POLICY IF EXISTS human_intervention_checkpoints_insert_rows ON public.human_intervention_checkpoints;
DROP POLICY IF EXISTS human_intervention_checkpoints_update_rows ON public.human_intervention_checkpoints;

-- ============================================================================
-- 4. ROOT TABLE POLICIES
-- ============================================================================

-- Workers
CREATE POLICY workers_select_own ON public.workers FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY workers_insert_own ON public.workers FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY workers_update_own ON public.workers FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY workers_delete_own ON public.workers FOR DELETE USING (owner_id = auth.uid());

-- Missions
CREATE POLICY missions_select_own ON public.missions FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY missions_insert_own ON public.missions FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY missions_update_own ON public.missions FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY missions_delete_own ON public.missions FOR DELETE USING (owner_id = auth.uid());

-- Approval Requests
CREATE POLICY approval_requests_select_own ON public.approval_requests FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY approval_requests_insert_own ON public.approval_requests FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY approval_requests_update_own ON public.approval_requests FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY approval_requests_delete_own ON public.approval_requests FOR DELETE USING (owner_id = auth.uid());

-- Identity Vault
CREATE POLICY identity_vault_select_own ON public.identity_vault FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY identity_vault_insert_own ON public.identity_vault FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY identity_vault_update_own ON public.identity_vault FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY identity_vault_delete_own ON public.identity_vault FOR DELETE USING (owner_id = auth.uid());

-- Notifications
CREATE POLICY notifications_select_own ON public.notifications FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY notifications_insert_own ON public.notifications FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY notifications_update_own ON public.notifications FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY notifications_delete_own ON public.notifications FOR DELETE USING (owner_id = auth.uid());

-- Memory Entries (legacy)
CREATE POLICY memory_entries_select_own ON public.memory_entries FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY memory_entries_insert_own ON public.memory_entries FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY memory_entries_update_own ON public.memory_entries FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY memory_entries_delete_own ON public.memory_entries FOR DELETE USING (owner_id = auth.uid());

-- Agent Memory Entries
CREATE POLICY agent_memory_entries_select_own ON public.agent_memory_entries FOR SELECT USING (owner_id = auth.uid());
CREATE POLICY agent_memory_entries_insert_own ON public.agent_memory_entries FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY agent_memory_entries_update_own ON public.agent_memory_entries FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY agent_memory_entries_delete_own ON public.agent_memory_entries FOR DELETE USING (owner_id = auth.uid());

-- Platform Connections (owner_id_uuid is authoritative; legacy TEXT owner_id is NOT trusted)
CREATE POLICY platform_connections_select_own ON public.platform_connections FOR SELECT USING (owner_id_uuid = auth.uid());
CREATE POLICY platform_connections_insert_own ON public.platform_connections FOR INSERT WITH CHECK (owner_id_uuid = auth.uid());
CREATE POLICY platform_connections_update_own ON public.platform_connections FOR UPDATE USING (owner_id_uuid = auth.uid()) WITH CHECK (owner_id_uuid = auth.uid());
CREATE POLICY platform_connections_delete_own ON public.platform_connections FOR DELETE USING (owner_id_uuid = auth.uid());

-- ============================================================================
-- 5. CHILD TABLE RLS (relationship-based ownership)
-- ============================================================================

ALTER TABLE public.mission_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atlas_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.worker_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.human_intervention_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.onboarding_workflows ENABLE ROW LEVEL SECURITY;

-- Drop permissive child policies
DROP POLICY IF EXISTS mission_steps_select_all_rows ON public.mission_steps;
DROP POLICY IF EXISTS mission_steps_insert_rows ON public.mission_steps;
DROP POLICY IF EXISTS mission_steps_update_rows ON public.mission_steps;
DROP POLICY IF EXISTS atlas_commands_select_all_rows ON public.atlas_commands;
DROP POLICY IF EXISTS atlas_commands_insert_rows ON public.atlas_commands;
DROP POLICY IF EXISTS atlas_commands_update_rows ON public.atlas_commands;
DROP POLICY IF EXISTS worker_responses_select_all_rows ON public.worker_responses;
DROP POLICY IF EXISTS worker_responses_insert_rows ON public.worker_responses;
DROP POLICY IF EXISTS worker_responses_update_rows ON public.worker_responses;
DROP POLICY IF EXISTS human_intervention_checkpoints_select_all_rows ON public.human_intervention_checkpoints;
DROP POLICY IF EXISTS human_intervention_checkpoints_insert_rows ON public.human_intervention_checkpoints;
DROP POLICY IF EXISTS human_intervention_checkpoints_update_rows ON public.human_intervention_checkpoints;
DROP POLICY IF EXISTS onboarding_workflows_select_all_rows ON public.onboarding_workflows;
DROP POLICY IF EXISTS onboarding_workflows_insert_rows ON public.onboarding_workflows;
DROP POLICY IF EXISTS onboarding_workflows_update_rows ON public.onboarding_workflows;

-- Mission Steps: owned via parent mission
CREATE POLICY mission_steps_select_own ON public.mission_steps FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = mission_steps.mission_id AND missions.owner_id = auth.uid())
);
CREATE POLICY mission_steps_insert_own ON public.mission_steps FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = mission_steps.mission_id AND missions.owner_id = auth.uid())
);
CREATE POLICY mission_steps_update_own ON public.mission_steps FOR UPDATE USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = mission_steps.mission_id AND missions.owner_id = auth.uid())
) WITH CHECK (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = mission_steps.mission_id AND missions.owner_id = auth.uid())
);
CREATE POLICY mission_steps_delete_own ON public.mission_steps FOR DELETE USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = mission_steps.mission_id AND missions.owner_id = auth.uid())
);

-- Atlas Commands: owned via parent mission
CREATE POLICY atlas_commands_select_own ON public.atlas_commands FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = atlas_commands.mission_id AND missions.owner_id = auth.uid())
);
CREATE POLICY atlas_commands_insert_own ON public.atlas_commands FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = atlas_commands.mission_id AND missions.owner_id = auth.uid())
);
CREATE POLICY atlas_commands_update_own ON public.atlas_commands FOR UPDATE USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = atlas_commands.mission_id AND missions.owner_id = auth.uid())
) WITH CHECK (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = atlas_commands.mission_id AND missions.owner_id = auth.uid())
);
CREATE POLICY atlas_commands_delete_own ON public.atlas_commands FOR DELETE USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = atlas_commands.mission_id AND missions.owner_id = auth.uid())
);

-- Worker Responses: primary via mission, fallback via worker
CREATE POLICY worker_responses_select_own ON public.worker_responses FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = worker_responses.mission_id AND missions.owner_id = auth.uid())
    OR
    EXISTS (SELECT 1 FROM public.workers WHERE workers.id = worker_responses.worker_id AND workers.owner_id = auth.uid())
);
CREATE POLICY worker_responses_insert_own ON public.worker_responses FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = worker_responses.mission_id AND missions.owner_id = auth.uid())
    OR
    EXISTS (SELECT 1 FROM public.workers WHERE workers.id = worker_responses.worker_id AND workers.owner_id = auth.uid())
);
CREATE POLICY worker_responses_update_own ON public.worker_responses FOR UPDATE USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = worker_responses.mission_id AND missions.owner_id = auth.uid())
    OR
    EXISTS (SELECT 1 FROM public.workers WHERE workers.id = worker_responses.worker_id AND workers.owner_id = auth.uid())
) WITH CHECK (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = worker_responses.mission_id AND missions.owner_id = auth.uid())
    OR
    EXISTS (SELECT 1 FROM public.workers WHERE workers.id = worker_responses.worker_id AND workers.owner_id = auth.uid())
);
CREATE POLICY worker_responses_delete_own ON public.worker_responses FOR DELETE USING (
    EXISTS (SELECT 1 FROM public.missions WHERE missions.id = worker_responses.mission_id AND missions.owner_id = auth.uid())
    OR
    EXISTS (SELECT 1 FROM public.workers WHERE workers.id = worker_responses.worker_id AND workers.owner_id = auth.uid())
);

-- Human Intervention Checkpoints: owned via parent mission (mission_id is TEXT, cast to UUID)
CREATE POLICY human_intervention_checkpoints_select_own ON public.human_intervention_checkpoints FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = human_intervention_checkpoints.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
);
CREATE POLICY human_intervention_checkpoints_insert_own ON public.human_intervention_checkpoints FOR INSERT WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = human_intervention_checkpoints.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
);
CREATE POLICY human_intervention_checkpoints_update_own ON public.human_intervention_checkpoints FOR UPDATE USING (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = human_intervention_checkpoints.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
) WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = human_intervention_checkpoints.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
);
CREATE POLICY human_intervention_checkpoints_delete_own ON public.human_intervention_checkpoints FOR DELETE USING (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = human_intervention_checkpoints.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
);

-- Onboarding Workflows: primary via mission, fallback via worker (mission_id and worker_id are TEXT)
CREATE POLICY onboarding_workflows_select_own ON public.onboarding_workflows FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = onboarding_workflows.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
    OR
    EXISTS (
        SELECT 1 FROM public.workers
        WHERE workers.id = onboarding_workflows.worker_id::UUID
        AND workers.owner_id = auth.uid()
    )
);
CREATE POLICY onboarding_workflows_insert_own ON public.onboarding_workflows FOR INSERT WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = onboarding_workflows.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
    OR
    EXISTS (
        SELECT 1 FROM public.workers
        WHERE workers.id = onboarding_workflows.worker_id::UUID
        AND workers.owner_id = auth.uid()
    )
);
CREATE POLICY onboarding_workflows_update_own ON public.onboarding_workflows FOR UPDATE USING (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = onboarding_workflows.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
    OR
    EXISTS (
        SELECT 1 FROM public.workers
        WHERE workers.id = onboarding_workflows.worker_id::UUID
        AND workers.owner_id = auth.uid()
    )
) WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = onboarding_workflows.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
    OR
    EXISTS (
        SELECT 1 FROM public.workers
        WHERE workers.id = onboarding_workflows.worker_id::UUID
        AND workers.owner_id = auth.uid()
    )
);
CREATE POLICY onboarding_workflows_delete_own ON public.onboarding_workflows FOR DELETE USING (
    EXISTS (
        SELECT 1 FROM public.missions
        WHERE missions.id = onboarding_workflows.mission_id::UUID
        AND missions.owner_id = auth.uid()
    )
    OR
    EXISTS (
        SELECT 1 FROM public.workers
        WHERE workers.id = onboarding_workflows.worker_id::UUID
        AND workers.owner_id = auth.uid()
    )
);

-- ============================================================================
-- 6. GRANTS
-- ============================================================================

-- Revoke broad access from anon on protected tables
REVOKE ALL ON public.workers FROM anon;
REVOKE ALL ON public.missions FROM anon;
REVOKE ALL ON public.approval_requests FROM anon;
REVOKE ALL ON public.identity_vault FROM anon;
REVOKE ALL ON public.notifications FROM anon;
REVOKE ALL ON public.memory_entries FROM anon;
REVOKE ALL ON public.agent_memory_entries FROM anon;
REVOKE ALL ON public.platform_connections FROM anon;
REVOKE ALL ON public.mission_steps FROM anon;
REVOKE ALL ON public.atlas_commands FROM anon;
REVOKE ALL ON public.worker_responses FROM anon;
REVOKE ALL ON public.human_intervention_checkpoints FROM anon;
REVOKE ALL ON public.onboarding_workflows FROM anon;

-- Grant appropriate DML to authenticated
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workers TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.missions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.approval_requests TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.identity_vault TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.notifications TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.memory_entries TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.agent_memory_entries TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.platform_connections TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.mission_steps TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.atlas_commands TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.worker_responses TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.human_intervention_checkpoints TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.onboarding_workflows TO authenticated;

-- Do NOT grant service_role for normal user requests

-- ============================================================================
-- 7. CLAIM RPC SECURITY
-- ============================================================================

-- Replace the claim RPC with a version that records the caller as owner.
-- The function remains SECURITY INVOKER so auth.uid() evaluates to the
-- authenticated caller. Anon execution is revoked below.
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
    INSERT INTO public.onboarding_workflows (
        id, mission_id, worker_id, platform, status,
        current_step, total_steps, checkpoint_data, step_history,
        started_by_approval_id, owner_id, created_at, updated_at
    ) VALUES (
        p_workflow_id, p_mission_id, p_worker_id, p_platform, p_status,
        p_current_step, p_total_steps,
        COALESCE(p_checkpoint_data, '{}'::jsonb),
        COALESCE(p_step_history, '[]'::jsonb),
        p_approval_id, auth.uid(), now(), now()
    )
    RETURNING * INTO v_inserted;

    RETURN QUERY SELECT to_jsonb(v_inserted), true;
    RETURN;
EXCEPTION
    WHEN unique_violation THEN
        SELECT * INTO v_existing
            FROM public.onboarding_workflows
            WHERE started_by_approval_id = p_approval_id
            LIMIT 1;
        IF NOT FOUND THEN
            RAISE;
        END IF;
        RETURN QUERY SELECT to_jsonb(v_existing), false;
        RETURN;
END;
$$;

-- Revoke execution from anon; keep only authenticated.
REVOKE ALL ON FUNCTION public.claim_onboarding_workflow_for_approval(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, JSONB, JSONB
) FROM anon;

GRANT EXECUTE ON FUNCTION public.claim_onboarding_workflow_for_approval(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, JSONB, JSONB
) TO authenticated;

-- ============================================================================
-- 8. DISABLE_RLS SCRIPT NEUTRALIZATION
-- ============================================================================

-- The legacy scripts/disable_rls.sql workaround is deprecated.
-- RLS must remain enabled on all protected tables.

-- ============================================================================
-- 9. NULL-OWNER QUARANTINE
-- ============================================================================

-- Existing rows with NULL owner_id remain quarantined.
-- RLS policies make NULL-owned rows invisible to normal authenticated users
-- because owner_id = auth.uid() evaluates to false when owner_id is NULL.
-- Do NOT assign fake UUIDs or auto-assign them to the current user.
-- A future controlled migration/admin process may re-assign ownership.

COMMIT;
