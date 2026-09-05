-- Sprint 7.2-C: P1-3 onboarding workflow restart idempotency.
--
-- Adds a nullable identifier linking an onboarding workflow to the
-- approval request that started it. A partial unique index guarantees
-- at most one onboarding workflow per approval_id. The partial index
-- allows legacy rows with NULL started_by_approval_id to remain valid
-- and prevents enforcing uniqueness until the column is populated.
--
-- The unique index is the database-authoritative idempotency boundary
-- for the start_onboarding flow. A companion plpgsql function
-- (claim_onboarding_workflow_for_approval) provides a race-free
-- get-or-create operation used by OnboardingWorkflowStore.
--
-- This migration is additive and does not backfill existing rows.
BEGIN;

ALTER TABLE public.onboarding_workflows
    ADD COLUMN IF NOT EXISTS started_by_approval_id UUID;

COMMENT ON COLUMN public.onboarding_workflows.started_by_approval_id IS
    'Approval request id that started this workflow. NULL for legacy rows or workflows not started through an approval. At most one workflow per non-null value (enforced by partial unique index).';

CREATE UNIQUE INDEX IF NOT EXISTS ux_onboarding_workflows_started_by_approval_id
    ON public.onboarding_workflows (started_by_approval_id)
    WHERE started_by_approval_id IS NOT NULL;

COMMIT;
