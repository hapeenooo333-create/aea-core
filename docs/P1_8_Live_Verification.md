# P1-8 Live Environment Verification

Verification date: 2026-09-11

## Environment

- GitHub repository: `hapeenooo333-create/aea-core` (requested repository; checkout at `be4f0de4e6767de1a3e94867a8df50f329d245a2`)
- Supabase project: `Affiliate-employee-ai` (documented identity only)
- Supabase project reference: `zzqtwebtujrvuywqhclx` (documented URL host only)
- Database connectivity: `NOT_VERIFIED` - the configured process had no `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_ANON_KEY`, or `SUPABASE_DB_URL`; DNS lookup for the documented host also failed.
- Authentication connectivity: `NOT_VERIFIED` - no configured client or reachable Auth endpoint was available.
- Environment status: `BLOCKED`

The repository does not contain `.env.example` or a tracked runtime `.env`. The
application reads `SUPABASE_KEY` first and `SUPABASE_ANON_KEY` as a fallback;
neither was present. No credential values were printed or persisted.

## Local Evidence

- P1-8 focused tests: `10 passed`.
- Full suite: `369 passed, 39 skipped`.
- `python -m compileall -q backend/app`: passed.
- `git diff --check`: passed.
- `HEAD == origin/main`: passed.
- The canonical Supabase migration and `database/migrations/` mirror have the
  same SQL semantics; differences are formatting-only.
- Source inspection confirms the P1-8 claim function is declared
  `SECURITY INVOKER`, grants execution to `authenticated`, revokes it from
  `anon`, and scopes claims with `owner_id = auth.uid()`.

These are local/source results, not live database results.

## Live Verification Classification

| Audit item | Classification | Evidence or limitation |
| --- | --- | --- |
| Supabase connectivity | `NOT_VERIFIED` | No runtime credentials; documented host DNS failed. |
| P1-8 migration | `NOT_VERIFIED` | Applied state cannot be queried; migration was not applied blindly. |
| Missions schema | `VERIFIED_LOCALLY` | Migration source contains the required durable fields; live schema unknown. |
| Orchestration events | `VERIFIED_LOCALLY` | Migration source defines the table, indexes, and policies; live behavior unknown. |
| RLS | `VERIFIED_LOCALLY` | Source defines event RLS and existing migrations define mission ownership; live enforcement unknown. |
| Authentication | `NOT_VERIFIED` | Auth endpoint and temporary users were unavailable. |
| Ownership | `VERIFIED_LOCALLY` | Application and migration source scope reads, writes, and claims by authenticated owner; live isolation unknown. |
| Claim RPC | `VERIFIED_LOCALLY` | Invoker declaration, owner check, terminal check, lease check, and fresh token persistence verified in source; live execution unknown. |
| Two-worker race | `NOT_VERIFIED` | No live Postgres connection; no in-memory result is substituted. |
| Stale lease recovery | `NOT_VERIFIED` | No live Postgres connection. |
| Idempotency | `VERIFIED_LOCALLY` | Local P1-8 tests pass; owner-scoped live uniqueness unknown. |
| Approval/HITL | `VERIFIED_LOCALLY` | Local P1-7 approval paths are covered; live approval infrastructure unavailable. |
| API endpoints | `VERIFIED_LOCALLY` | Local route tests pass; live authentication, ownership, and persistence unknown. |
| Pinterest | `NOT_VERIFIED` | No explicitly configured live Pinterest environment was available. Provider-level exactly-once semantics are not claimed. |
| Secret sanitization | `VERIFIED_LOCALLY` | Source and local tests cover sanitized payloads; no secrets were emitted during this audit. |
| Cleanup | `DETERMINISTICALLY_SIMULATED` | No live test data or users were created, so no production cleanup was required. |

## Required Next Step

Provide the verification runner with a correctly scoped target environment
through its process environment, without sending credentials in chat or logs:

- `SUPABASE_URL` for the intended project;
- `SUPABASE_KEY` or `SUPABASE_ANON_KEY` containing the publishable/anon key;
- a reachable Supabase API and Auth service; and
- an approved administrative database connection only if migration/schema
  inspection requires it.

After that prerequisite is available, rerun the live procedure with ephemeral
Auth users and execute the migration only after checking its applied state.

## Production Readiness

`BLOCKED`

Live schema state, RLS enforcement, authenticated API behavior, the real
two-worker race, stale-lease fencing, live idempotency, and cleanup remain
unverified. No production migration or destructive operation was attempted.