# Decision.md — Factory Traffic Management System

Project: CSI Smart Tech Backend Developer Intern Assessment V2
Owner: Emon · Architect: Claude · Log started: 2026-10-08

## How this file works

- **FIXED** — chosen by the owner. Not up for debate.
- **APPROVED** — proposed by the architect, approved by the owner on 2026-10-08 ("approve all").
- **PROPOSED** — architect's default, **not yet approved**. Agents may implement it behind config or an isolated seam, but must not treat it as final.
- Nobody (human or agent) changes an APPROVED decision silently. To change one: add a row to the Change Log, edit the entry, and say why.
- Each decision has an ID. Code comments and tests that depend on a decision cite it (example: `# D-08`).

---

## 1. Fixed by owner

### D-00 · Stack — FIXED
Frontend Next.js (TypeScript, App Router) · Backend FastAPI (Python 3.12) · Database PostgreSQL 16.

### D-22 · Git checkpoints need owner approval — FIXED
After every completed subtask, the agent asks the owner whether to `git add`, commit and push. It pushes only if the owner approves that subtask. Details are in Instruction.md section 1 ("Git checkpoint protocol"). (D-21 is kept free for the MVC question.)

---

## 2. Approved decisions

### A. Architecture

**D-01 · One serialized worker per junction — APPROVED**
- Decision: every event for a junction (sensor event, command, controller ACK, timer tick) is put on one in-process queue per junction. A single worker consumes it, so two decisions about the same junction never run at the same time. Postgres stores the state; a `version` column on the state row is a second guard.
- Why: the spec forbids `sleep()` in handlers and requires no conflicting results from concurrent requests. A single-writer loop gives deterministic ordering and makes timers just another event.
- Trade-off: one backend process only. Running several processes would need Postgres advisory locks per junction.
- Rejected: `SELECT ... FOR UPDATE` per request (timers become awkward, more lock contention); optimistic locking alone (retry storms on bursts).

**D-02 · Pure domain engine — APPROVED**
- Decision: the engine is a function `(state, event, now) -> (new_state, effects)`. No I/O, no DB, no HTTP, no MQTT, no `datetime.now()`. Time comes in as a parameter. Effects (send command, write audit, notify) are returned as data and executed by the application layer.
- Why: the spec asks for logic testable without HTTP, a browser, MQTT or hardware. This is also how we prove the safety rules with property tests.

**D-03 · Queues are vehicle rows, not counters — APPROVED**
- Decision: each detected vehicle is a row with status WAITING or CLEARED. Queue size = count of WAITING rows per direction.
- Why: clearing a vehicle by `vehicle_id` is idempotent, the count cannot go below 0, and we get per-vehicle priority and wait time for scheduling.

**D-04 · Controller port + REST simulator — APPROVED**
- Decision: the domain talks to a `ControllerPort` interface. The first adapter is a REST-driven simulator. MQTT is optional bonus work and must be addable without touching the domain.

**D-05 · Live updates over SSE, polling fallback — APPROVED**
- Decision: the dashboard uses Server-Sent Events. If SSE fails twice in a row, it falls back to polling every 2 seconds.
- Why: updates only flow server to browser, so SSE is enough and simpler than WebSocket. The fallback keeps the demo working behind proxies.

**D-06 · Stack details — APPROVED**
- SQLAlchemy 2.0 (async) + psycopg 3, Alembic migrations, Pydantic v2, pytest + pytest-asyncio + hypothesis, Docker Compose for Postgres/backend/frontend.

### B. Signals and scheduling

**D-07 · Timings, all configurable per junction — APPROVED**
- GREEN 30s · YELLOW 5s · ALL_RED 2s (spec gives no value; 2s is our assumption) · minimum green 10s · maximum green 60s.
- Stored in junction config, never hard-coded in engine logic.

**D-08 · Confirm-before-proceed — APPROVED**
- Decision: the engine never emits GREEN for a phase until the opposing phase's RED is **confirmed** by a controller ACK. Each step of a transition (YELLOW, RED, GREEN) waits for its ACKs before the next step or timer starts.
- Why: the spec says an unconfirmed command must never be assumed executed. This is the core safety rule.

**D-09 · Scheduling score — APPROVED**
- Phase score = sum of vehicle weights (TRUCK 3, FORKLIFT 2, EMPLOYEE_VEHICLE 1) + waiting-time factor.
- Switch only if the challenger beats the current phase by 25%, or the current phase has no waiting vehicles (after minimum green).
- Anything waiting more than 90s is forced next (starvation protection).
- No traffic anywhere: stay on the current phase, do not cycle.
- EMERGENCY is not scored; it triggers preemption (see D-15).

**D-10 · Phases and config validation — APPROVED**
- Two phases only: NORTH+SOUTH and EAST+WEST. No turning movements.
- `POST /api/junctions` validates config: every direction belongs to exactly one phase, and the two phases are declared conflicting. Invalid config returns 422.

### C. Sensor events

**D-11 · `event_id` decides duplicates — APPROVED**
- Unique DB constraint on `event_id`. Duplicate returns 200 with `duplicate: true` and writes an audit entry; state is untouched.
- `sequence_no` is used only to detect out-of-order events, tracked per (junction, direction), because the spec has no sensor ID.

**D-12 · Server time drives decisions — APPROVED**
- Server-received time is used for wait time and scheduling. Sensor timestamp is stored for audit.
- If sensor time differs from server time by more than 5 minutes, the event is flagged stale: recorded in audit, does not change queues or trigger emergencies.

**D-13 · Orphan clears — APPROVED**
- A CLEARED event for an unknown vehicle creates a CLEARED marker and changes no count. A late ARRIVED for that vehicle is then ignored instead of resurrecting it. See P-01 for the exact ordering rule (pending).

**D-14 · Unknown vehicle types rejected — APPROVED**
- Anything outside FORKLIFT, TRUCK, EMPLOYEE_VEHICLE, EMERGENCY gets 422. No guessing a mapping for "material-carrying vehicle". Logged as a spec issue.

### D. Emergency and manual

**D-15 · Emergency overrides manual — APPROVED**
- Emergency preemption always uses YELLOW → ALL_RED → GREEN. It never skips the sequence.
- When the emergency ends, the junction returns to AUTOMATIC. The admin must re-issue manual control, so nobody inherits an old override.

**D-16 · Competing emergencies — APPROVED**
- First come, first served by server time. An active emergency phase is never preempted by a later emergency (avoids flip-flopping).
- Emergencies on the same phase (NORTH and SOUTH) are served together. The conflicting one is served next.

**D-17 · Emergency cleared — APPROVED**
- Cleared when its VEHICLE_CLEARED arrives, or after a 120s timeout (stale emergency). Both write an audit entry.

**D-18 · Manual lease — APPROVED**
- Manual control is a 5-minute lease. Each valid admin command renews it. When it expires, the junction returns to AUTOMATIC. An admin disconnecting needs no special handling: the lease just expires.
- Two admins at once: the last valid command wins; both are audited with `issued_by`.
- Known gap: no authentication, so `issued_by` is free text. Documented in the README.

### E. Failure and recovery

**D-19 · Controller failure handling — APPROVED**
- ACK timeout 3s, up to 2 retries with the same `command_id`.
- After that: junction becomes DEGRADED, actual state becomes UNKNOWN, no GREEN is issued, engine requests ALL_RED as the fail-safe, UI shows a "manual traffic marshal required" warning.
- Duplicate ACK: ignored. Late ACK: updates actual state but does not revive the cancelled transition. Unknown `command_id`: 404 and logged.
- Controller reconnect: stay DEGRADED until actual state is confirmed, then restart from ALL_RED.
- Sensor offline: that direction's queue is marked stale and gets a minimum fairness slot in scheduling.

**D-20 · Restart recovery — APPROVED**
- On boot: load the saved state, set every actual state to UNKNOWN, mark pending commands ABANDONED, tell the controller ALL_RED and wait for confirmation, then enter AUTOMATIC with fresh timers.
- Manual mode and its remaining lease are kept. Emergency is re-derived from WAITING EMERGENCY vehicles.

---

## 3. Approved at Gate 1 (P-01 .. P-04) — APPROVED

These details were proposed by the architect and approved by the owner at Gate 1 review on 2026-10-08.

**P-01 · Orphan-clear ordering rule (refines D-13) — APPROVED**
- A CLEARED marker stores its `sequence_no`. A later ARRIVED for the same `vehicle_id` and direction is ignored only if its `sequence_no` is lower than the marker's. A higher `sequence_no` is a genuine new visit (forklifts loop around the factory) and creates a new WAITING row.
- Uniqueness: one WAITING row per (junction, vehicle_id), enforced by a partial unique index.

**P-02 · HTTP status mapping and extra endpoints — APPROVED**
- Sensor event: 201 applied · 200 duplicate (`duplicate: true`) · 202 recorded but not applied (stale or orphan clear, with `reason`) · 404 unknown junction · 422 invalid or unknown vehicle type.
- Command: 202 accepted (transition may still be running) · 404 unknown junction · 409 not allowed in current state (e.g. junction DEGRADED) · 422 invalid command or direction.
- Controller event: 200 processed · 200 duplicate ACK ignored · 404 unknown `command_id`.
- Added endpoints (spec allows this if explained): `GET /api/junctions/{id}/stream` (SSE), `POST /api/device-status` (the spec's status-event example has no URL), `POST /api/simulator/{id}/mode` (switch the simulated controller between AUTO_ACK, DELAYED, SILENT, OFFLINE for demos).

**P-03 · Timer constants — APPROVED**
- Tick interval 500ms. Retry spacing 3s (same as ACK timeout). SSE heartbeat every 15s.

**P-04 · Behaviour while DEGRADED — APPROVED**
- Sensor events and emergencies are still recorded and shown, but cause no signal action. Manual commands get 409. `RETURN_TO_AUTOMATIC` is accepted but has no effect until the controller is confirmed again.

---

## 4. Spec issues to put in the README

Section title must be exactly: **Assumptions / Questions / Requirement Issues**

| # | Issue | Our handling |
|---|---|---|
| S-1 | "Immediately begin" emergency preemption conflicts with YELLOW 5s + ALL_RED 2s: GREEN cannot come in under 7s | "Immediately" means the transition starts at once; the UI shows the countdown (D-15) |
| S-2 | `sequence_no` has no sensor ID, so its scope is undefined | Scoped per (junction, direction) (D-11) |
| S-3 | `VEHICLE_CLEARED` has no `vehicle_type`; type must come from the arrival record, which may be missing | Look up by `vehicle_id`; orphan clear handled by D-13 |
| S-4 | `POST /api/junctions` could create an unsafe configuration | Config validation (D-10) |
| S-5 | Scenario lists "material-carrying vehicles" but only 4 types are supported | Reject with 422 (D-14) |
| S-6 | ALL_RED duration not given | Assumed 2s, configurable (D-07) |
| S-7 | Status-event example has no endpoint | Added `POST /api/device-status` (P-02) |
| S-8 | No authentication, but manual control is a safety-relevant action | Free-text `issued_by`; documented gap (D-18) |
| S-9 | RED/YELLOW/GREEN only: no flashing state for failure | DEGRADED requests ALL_RED and asks for a human marshal (D-19) |

---

## 5. Change log

| Date | ID | Change | By |
|---|---|---|---|
| 2026-10-08 | D-00 | Stack fixed | Owner |
| 2026-10-08 | D-01 – D-20 | Approved ("approve all") | Owner |
| 2026-10-08 | P-01 – P-04 | Proposed, awaiting approval | Architect |
| 2026-10-08 | D-22 | Git checkpoint rule added (ask before every push) | Owner |
| 2026-10-08 | P-01 – P-04 | Approved at Gate 1 review | Owner |
