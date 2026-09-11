# P1-8 Orchestration

P1-8 adds a bounded employee orchestration layer for affiliate jobs. It owns
mission lifecycle, deterministic priority, scheduling timestamps, dependency
readiness, operational events, and concise reports. It delegates actual work
to the existing `EmployeeVerticalSlice` and therefore does not introduce a
second execution engine.

The authenticated API is mounted under `/employee`:

- `POST /employee/objective`
- `GET /employee/missions`
- `GET /employee/missions/{mission_id}`
- `GET /employee/missions/next`
- `POST /employee/missions/{mission_id}/run`
- `POST /employee/missions/{mission_id}/pause`
- `POST /employee/missions/{mission_id}/resume`
- `POST /employee/missions/{mission_id}/schedule`
- `POST /employee/missions/{mission_id}/cancel`
- `GET /employee/status`
- `GET /employee/report`
- `GET /employee/missions/{mission_id}/events`

Mission selection is deterministic and records operational reasons, including
priority score, urgency, readiness, dependency blocking, schedule, and age.
Sensitive actions continue through the P1-7 approval and human-intervention
paths. Mission claims use an owner-scoped, expiring orchestration lease before
delegating to P1-7D step claims.

Local deterministic tests cover lifecycle, scheduling, dependency readiness,
duplicate objective submission, two-worker selection, API ownership, reports,
and secret sanitization. Live Supabase and Pinterest verification remain
environment-gated and are never represented as local test evidence.