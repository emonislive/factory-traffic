# Instruction.md — Antigravity Agent Playbook

Project: Factory Traffic Management System (CSI Smart Tech, Backend Intern Assessment V2)
Stack: Next.js (TypeScript) · FastAPI (Python 3.12) · PostgreSQL 16
Source of truth for choices: `Decision.md`. Source of truth for requirements: the assessment PDF.

---

## 0. How to use this file

1. Put `Decision.md`, `Instruction.md` and the assessment PDF (`docs/assessment.pdf`) in the repo root before starting any agent.
2. Run agents in the order in section 4. Phase 0 runs alone. Phase 1 agents (A, B, C, D, E) run **in parallel**, one Antigravity agent each.
3. Give each agent its prompt from section 6, word for word. Every prompt starts with "Read Decision.md and Instruction.md sections 1, 2 and 3".
4. Isolate parallel work. Use one git branch per agent (`agent/domain`, `agent/api`, `agent/runtime`, `agent/web`, `agent/qa`). If your Antigravity version can give each agent its own workspace or worktree, use that; otherwise keep agents on separate branches and merge in Phase 2.
5. Two human gates: **Gate 1** after Phase 0 (you review contracts), **Gate 2** after Phase 2 (you run the demo and read the code). Do not skip them. You must be able to explain this system in the technical review.

---

## 1. Ground rules for every agent

1. **No new decisions.** If something is ambiguous and not covered by `Decision.md`, stop that piece of work, append an entry to `PENDING_DECISIONS.md` (what, options, your recommendation, why), and continue with other work. The human decides. Items marked PROPOSED in `Decision.md` may be implemented behind config or an isolated seam, but are not final.
2. **Stay in your lane.** Only edit the files your agent owns (section 3). Need a change elsewhere? Write it in `PENDING_DECISIONS.md` under "Cross-agent requests". Never edit another agent's files.
3. **Contracts are frozen after Gate 1.** Do not change `contracts/` (OpenAPI, domain types, DB schema). Request changes through `PENDING_DECISIONS.md`.
4. **Safety beats features.** A smaller system that never breaks an invariant (section 2) beats a bigger one that might. If you are short on time, cut features, never invariants or tests.
5. **Plain-language comments.** Comments explain *why* in simple words. No jargon walls. (Owner preference.)
6. **Cite decisions.** When code implements a decision, add `# D-08` style comments. Tests cite the invariant they check (`INV-3`).
7. **No hidden global state, no `sleep()` in request handlers, no `datetime.now()` in the domain.**
8. **Log usefully.** Structured logs with `junction_id`, `event_id`, `command_id` where relevant. No `print`.
9. **Fix your own mistakes out loud.** Follow the self-correction protocol in section 7. Every bug you fix gets a regression test and a `MISTAKES.md` entry.
10. **Finish with evidence.** Your final message must list: what you built, test command and result, invariants you checked, entries you added to `MISTAKES.md` and `PENDING_DECISIONS.md`.
11. **Ask before every git push.** After each completed subtask, stop and ask the owner whether to `git add`, commit and push. Push only after an explicit "yes" (D-22). Follow the checkpoint protocol below.

### Git checkpoint protocol (D-22)

A **subtask** is one finished item from your prompt (for example "scoring.py with tests", "one router with its tests", "one bug fix with its regression test").

Ask only when the subtask is really done: your tests pass, ruff/mypy (or frontend build and lint) are clean, and the self-check loop in section 7 found nothing open. If something still fails, say so and keep working. Do not ask for a commit on broken work.

When it is done, **do not run any git write command yet.** Run only read-only commands (`git status --short`, `git diff --stat`, `git branch --show-current`) and then ask the owner this, filled in:

```
Subtask done: <one line>
Branch: <current branch>
Files changed: <git status --short output>
Tests: <command and result>
Proposed commit message: <type>(<area>): <short summary>

Do you want me to git add, commit and push this? (yes / no / change the message)
```

Then:
- **"yes"**: run `git add` on the listed files only (never `git add .` or `-A`), `git commit -m "<message>"`, then `git push` (first push on a branch: `git push -u origin <branch>`). Report the commit hash and the result of the push.
- **"no"** or no answer: do not commit or push. Keep working on the next subtask, and list the unpushed subtasks when you ask next time.
- **"change the message"**: use the owner's message, then proceed as for "yes".

Hard limits:
- Never push without a "yes" for that specific subtask. An earlier "yes" does not cover later work.
- Never force-push, rewrite history, delete branches, or push to `main`/`master`. Push only to your own agent branch.
- Never stage `.env` files, secrets, or `docs/assessment.pdf` (it is the company's document). If one of them shows up in `git status`, tell the owner instead of staging it.
- If the push fails (auth, conflict, rejected), report the exact error and stop. Do not try to work around it.

Owner tip: check Antigravity's terminal-command approval setting and make sure `git push` needs your review before it runs. That is a second lock in case an agent forgets this rule.

---

## 2. Safety invariants (must hold at all times)

| ID | Invariant |
|---|---|
| INV-1 | NORTH/SOUTH and EAST/WEST are never GREEN at the same time, in **desired** state. |
| INV-2 | A GREEN command for phase X is only emitted when the opposing phase's RED is **confirmed** by ACK (D-08). |
| INV-3 | A GREEN phase never goes directly to the conflicting GREEN. The sequence is always: GREEN → YELLOW → RED (ALL_RED hold) → GREEN. |
| INV-4 | Manual and emergency requests use the same transition sequence. They never bypass it. |
| INV-5 | Invalid or unexpected input (bad command, unknown junction, duplicate, stale, unknown `command_id`) never changes signal state to anything unsafe. |
| INV-6 | Queue counts are never negative. Processing the same `event_id` twice changes the queue once. |
| INV-7 | An unconfirmed command is never treated as executed. Actual state stays UNKNOWN until an ACK or a controller state report says otherwise. |
| INV-8 | After restart, no previously requested signal state is assumed correct (D-20). |
| INV-9 | In DEGRADED mode no GREEN command is emitted. |

The domain agent turns these into property tests (hypothesis): feed random sequences of events, commands, ACKs, timeouts and ticks, and assert every invariant after every step.

---

## 3. Repo layout and ownership

```
factory-traffic/
├─ Decision.md                 (owner + architect)
├─ Instruction.md              (owner + architect)
├─ MISTAKES.md                 (all agents append)
├─ PENDING_DECISIONS.md        (all agents append)
├─ README.md                   (Agent E, final assembly)
├─ docker-compose.yml          (Agent 0)
├─ docs/assessment.pdf
├─ contracts/                  (Agent 0, then frozen)
│  ├─ openapi.yaml
│  ├─ domain_types.py          shared dataclasses/enums (copied into backend/app/domain/types.py)
│  ├─ schema.sql               reference DDL
│  └─ sse.md                   stream format
├─ backend/
│  ├─ pyproject.toml
│  ├─ alembic/                          (Agent B)
│  ├─ app/
│  │  ├─ domain/                        (Agent A)  pure logic, no I/O
│  │  │  ├─ types.py  config.py  engine.py  scoring.py  events.py  effects.py  ports.py
│  │  ├─ application/                   (Agent C)  runtime around the engine
│  │  │  ├─ junction_worker.py   per-junction queue + loop (D-01)
│  │  │  ├─ ticker.py            emits Tick events every 500ms
│  │  │  ├─ command_tracker.py   ACK timeout, retry, duplicate ACK (D-19)
│  │  │  ├─ recovery.py          boot recovery (D-20)
│  │  │  └─ effect_executor.py   runs effects returned by the engine
│  │  ├─ infrastructure/
│  │  │  ├─ db/ models.py repositories.py session.py     (Agent B)
│  │  │  └─ controllers/ rest_simulator.py               (Agent C)
│  │  ├─ api/                           (Agent B)  routers, schemas, error handlers, SSE
│  │  └─ main.py                        (Agent B wires, Agent C provides startup hooks)
│  └─ tests/
│     ├─ domain/                        (Agent A)
│     ├─ application/                   (Agent C)
│     ├─ api/                           (Agent B)
│     └─ scenarios/                     (Agent E)  the 9 assessment scenarios
└─ frontend/                            (Agent D)  Next.js App Router, TypeScript
```

Dependency direction: `api → application → domain ← infrastructure`. The domain imports nothing from the other folders.

---

## 4. Phase plan

| Phase | Who | Time | Output |
|---|---|---|---|
| 0 | Agent 0 (scaffold + contracts) | ~25 min | Repo skeleton, compose, contracts, stubs, empty test setup |
| **Gate 1** | You | ~15 min | Read contracts, answer `PENDING_DECISIONS.md`, approve P-01..P-04 |
| 1 | Agents A, B, C, D, E in parallel | ~2 h | Each agent's deliverables on its own branch |
| 2 | Agent E (integration) | ~45 min | Merge branches, run all scenarios, adversarial review, README |
| **Gate 2** | You | ~30 min | Run the demo, read the code, rehearse explanations |

Merge order in Phase 2: A → B → C → D (domain first, since everything depends on it).

---

## 5. Contracts

### 5.1 Domain model (Agent 0 writes these as typed stubs)

- Enums: `Direction {NORTH,SOUTH,EAST,WEST}` · `Phase {NS, EW}` · `Signal {RED,YELLOW,GREEN,UNKNOWN}` · `Mode {AUTOMATIC,MANUAL,EMERGENCY,DEGRADED}` · `VehicleType {EMERGENCY,TRUCK,FORKLIFT,EMPLOYEE_VEHICLE}` · `Step {BOOT, GREEN, YELLOW, ALL_RED}` · `CommandStatus {PENDING,ACKED,FAILED,ABANDONED}`.
- `JunctionConfig`: `id`, `name`, `phases: {NS:[NORTH,SOUTH], EW:[EAST,WEST]}`, `timings` (green, yellow, all_red, min_green, max_green, ack_timeout, max_retries, starvation_after, emergency_timeout, manual_lease, stale_event_after), `vehicle_weights`.
- `JunctionState`: `version`, `mode`, `serving` (Phase currently or last green), `step`, `target` (Phase or None), `deadline_at`, `desired{dir:Signal}`, `actual{dir:Signal}`, `pending_command_ids`, `manual{active, lease_expires_at, target_phase, issued_by}`, `emergencies[{vehicle_id, direction, phase, detected_at, expires_at}]`, `waiting_vehicles` (read-only snapshot for scoring), `alerts[]`.
- Inputs to the engine (`events.py`): `VehicleArrived`, `VehicleCleared`, `AdminCommand`, `ControllerAck`, `ControllerNack`, `DeviceStatusChanged`, `Tick`, `Boot`.
- Outputs (`effects.py`): `SendSignalCommand(command_id, direction, requested_state)`, `RecordAudit(...)`, `ScheduleNothing` (timers live in state as `deadline_at`, so nothing to schedule), `Alert(...)`.
- Ports (`ports.py`): `ControllerPort.send(command)`, `Clock.now()`, `IdGenerator.new_command_id()`. The engine receives ids and time from outside.

### 5.2 Transition sequence (the state machine)

Switching from serving phase S to target phase T:

1. Emit YELLOW for every direction of S. Wait for all ACKs. *(desired = YELLOW)*
2. On the last ACK: `deadline = now + yellow`.
3. On Tick ≥ deadline: emit RED for S. Wait for all ACKs.
4. On the last ACK: step = ALL_RED, `deadline = now + all_red`.
5. On Tick ≥ deadline **and** actual(S) is RED (INV-2): emit GREEN for T. Wait for all ACKs.
6. On the last ACK: step = GREEN, `serving = T`, `deadline = now + green`.

Failure: any step waiting for ACK past `ack_timeout` → resend with the same `command_id` (max 2 retries) → then DEGRADED (D-19). Late/duplicate ACKs follow D-19.

Mode rules: AUTOMATIC picks the target by score (D-09). MANUAL holds the requested phase until the lease ends (D-18). EMERGENCY targets the emergency phase and holds it until cleared or timed out (D-15, D-16, D-17). DEGRADED emits no GREEN (INV-9).

### 5.3 REST API (Agent 0 writes `contracts/openapi.yaml`; status codes follow P-02)

| Method + path | Purpose | Success | Errors |
|---|---|---|---|
| GET `/api/junctions` | list | 200 | |
| GET `/api/junctions/{id}` | config + summary | 200 | 404 |
| POST `/api/junctions` | create (validated, D-10) | 201 | 409 exists, 422 |
| POST `/api/sensor-events` | vehicle arrived/cleared | 201 applied, 200 duplicate, 202 not applied (`reason`) | 404, 422 |
| GET `/api/junctions/{id}/status` | live status | 200 | 404 |
| POST `/api/junctions/{id}/commands` | `MANUAL_GREEN_REQUEST`, `RETURN_TO_AUTOMATIC` (+ `issued_by`) | 202 | 404, 409, 422 |
| POST `/api/controller-events` | ACK / NACK / controller online-offline | 200 | 404 unknown `command_id`, 422 |
| POST `/api/device-status` | sensor/controller status event | 200 | 404, 422 |
| GET `/api/junctions/{id}/history` | audit log (`limit`, `before_id`, `event_type`) | 200 | 404 |
| GET `/api/junctions/{id}/stream` | SSE | 200 | 404 |
| POST `/api/simulator/{id}/mode` | `AUTO_ACK` / `DELAYED` / `SILENT` / `OFFLINE` | 200 | 404, 422 |

Status payload = the assessment's example **plus**: `transition {step, target, deadline_at}`, `pending_commands[]`, `emergency {active, direction, vehicle_id}`, `manual {active, lease_expires_at, issued_by}`, `alerts[]`, `device_statuses`, `stale_queues[]`. Alert types: `CONTROLLER_OFFLINE`, `SIGNAL_FAILURE`, `SENSOR_FAILURE`, `STATE_MISMATCH`, `COMMAND_TIMEOUT`, `UNKNOWN_DEVICE_STATE`.

Errors use one shape everywhere: `{"error": {"code": "JUNCTION_DEGRADED", "message": "...", "details": {}}}`.

### 5.4 Database (Agent 0 writes `contracts/schema.sql`, Agent B turns it into Alembic migrations)

- `junctions(id pk, name, config jsonb, created_at)`
- `junction_state(junction_id pk fk, version int, mode, serving, step, target, deadline_at, desired jsonb, actual jsonb, manual jsonb, emergencies jsonb, updated_at)`
- `vehicles(id pk, junction_id fk, vehicle_id, direction, vehicle_type, status, arrival_seq, clear_seq, arrived_server_at, arrived_sensor_at, cleared_server_at)` + partial unique index on `(junction_id, vehicle_id) WHERE status='WAITING'` (P-01)
- `processed_events(event_id pk, junction_id, received_at, outcome, payload jsonb)`
- `direction_sequence(junction_id, direction, last_sequence_no, pk(junction_id, direction))`
- `commands(command_id pk, junction_id, direction, requested_state, status, attempts, sent_at, deadline_at, acked_at, actual_state)`
- `device_status(junction_id, device_type, direction, status, updated_at)`
- `audit_log(id bigserial pk, junction_id, event_type, direction, previous_state, new_state, command_id, reason, payload jsonb, occurred_at, source)` — append-only, no UPDATE or DELETE in code.

Write path rule (Agent B + C): the worker applies one event, then saves state + commands + audit + processed event **in one DB transaction**. If the transaction fails, the effects are not executed.

### 5.5 SSE format (`contracts/sse.md`)

`event: status` with the full status payload as JSON, sent after every committed state change. A comment line `: ping` every 15 seconds. The client may reconnect at any time and gets a fresh `status` first.

---

## 6. Agent prompts (copy and paste)

### Agent 0 — Architect / Scaffold (Phase 0, runs alone)

```
You are the scaffolding architect for the Factory Traffic Management System.
Read Decision.md fully, and Instruction.md sections 1, 2, 3, 5. Read docs/assessment.pdf.

Build ONLY the skeleton and contracts. No business logic.
1. Create the repo layout from Instruction.md section 3, with empty modules and docstrings.
2. backend/pyproject.toml (FastAPI, SQLAlchemy 2 async, psycopg 3, alembic, pydantic v2, pytest, pytest-asyncio, hypothesis, httpx, ruff, mypy). frontend: create-next-app (TypeScript, App Router).
3. docker-compose.yml: postgres:16, backend, frontend, healthchecks, env files (.env.example).
4. contracts/: openapi.yaml (all endpoints in 5.3, error shape, examples), domain_types.py (5.1 as typed dataclasses and enums), schema.sql (5.4), sse.md (5.5). Copy domain_types.py into backend/app/domain/types.py.
5. Create MISTAKES.md and PENDING_DECISIONS.md with the templates from Instruction.md section 7.
6. A Makefile with: up, down, test-domain, test-all, lint, migrate, seed.
7. Verify: `docker compose up -d db` works, `pytest` collects 0 tests without error, `ruff` and `mypy` pass on stubs, `npm run build` passes.

Do not decide anything not in Decision.md; log it in PENDING_DECISIONS.md.
Finish with the evidence list from rule 10.
```

### Agent A — Domain Engine

```
You own backend/app/domain/ and backend/tests/domain/. Read Decision.md, Instruction.md sections 1, 2, 3, 5.1, 5.2.

Implement the pure traffic engine: engine.py (state machine in 5.2), scoring.py (D-09), config validation (D-10), event handling for arrivals/clears (D-03, D-11..D-14, P-01), emergency policy (D-15..D-17), manual lease (D-18), failure handling (D-19), boot recovery transition (D-20).
Rules: no I/O, no imports from application/infrastructure/api, no datetime.now(), no random without an injected generator. Engine signature: (state, event, now) -> (new_state, effects).

Tests (must exist, must pass):
- One unit test per decision D-07..D-20.
- Property tests (hypothesis) for INV-1..INV-9: random sequences of arrivals, clears, admin commands, ACKs, NACKs, ticks, status changes. Check invariants after every step.
- Specific cases: emergency during manual, two conflicting emergencies, repeated emergency event, emergency timeout, ACK never arrives, late ACK, duplicate ACK, restart mid-transition, starvation (a lone EMPLOYEE_VEHICLE waiting 91s gets served), no cycling with empty queues.

Self-check loop (repeat until clean): run tests, run mypy and ruff, re-read your diff against each cited decision, try to break your own engine with a new hypothesis strategy. Log every bug you find in MISTAKES.md with a regression test.
Finish with the evidence list from rule 10.
```

### Agent B — Persistence and API

```
You own backend/alembic/, backend/app/infrastructure/db/, backend/app/api/, backend/tests/api/. Read Decision.md, Instruction.md sections 1, 2, 3, 5.3, 5.4, 5.5.

Build: Alembic migrations from contracts/schema.sql; async repositories (state, vehicles, processed events, commands, audit, device status); FastAPI routers and Pydantic schemas exactly matching contracts/openapi.yaml and status codes in P-02; one error shape; CORS for the Next.js origin; SSE endpoint; seed script that creates Junction A.
Routers must be thin: validate input, hand it to the junction worker (Agent C provides `submit(event) -> result`), map the result to HTTP. No traffic rules in routers.
Until Agent C's worker exists, code against a fake worker with the same interface.

Tests: validation errors (missing, malformed, unknown junction, unknown vehicle type), duplicate event returns 200 and changes nothing, status codes per P-02, history pagination and filters, SSE sends a first status event, migrations apply on an empty DB, audit_log has no update/delete code paths.

Self-check loop: run tests against real Postgres from compose, compare every response against openapi.yaml, re-read your diff for any rule that belongs in the domain and move it out (log it).
Finish with the evidence list from rule 10.
```

### Agent C — Runtime, Controller and Recovery

```
You own backend/app/application/, backend/app/infrastructure/controllers/, backend/tests/application/. Read Decision.md, Instruction.md sections 1, 2, 3, 5.1, 5.2, 5.4.

Build: junction_worker.py (one asyncio queue + one consumer task per junction; `submit(event)` returns the result of processing; D-01), ticker.py (Tick every 500ms, P-03), effect_executor.py (runs engine effects after the DB transaction commits), command_tracker.py (ACK timeout, same-command_id retries, duplicate/late ACK, D-19), recovery.py (boot sequence D-20), rest_simulator.py (a ControllerPort adapter with modes AUTO_ACK, DELAYED, SILENT, OFFLINE, switchable at runtime).
Keep the MQTT door open: nothing in application/ may import the simulator directly, only ControllerPort.

Tests: the concurrency scenario from the assessment (T=0 truck N, T=4ms emergency E, T=8ms manual W, T=12ms duplicate emergency E, T=17ms ACK) run with asyncio.gather; assert INV-1..INV-9 and a sensible final state. Also: SILENT controller leads to DEGRADED after 2 retries; OFFLINE then reconnect leads to ALL_RED then AUTOMATIC; kill the worker mid-transition and recover; 200 random events across 2 junctions never block each other (D-01, multi-junction).

Self-check loop: run tests 20 times in a row to catch flaky races, grep for `sleep(` inside request paths, re-read the diff against D-01, D-19, D-20. Log mistakes.
Finish with the evidence list from rule 10.
```

### Agent D — Frontend (Next.js)

```
You own frontend/. Read Decision.md, Instruction.md sections 1, 3, 5.3, 5.5, and assessment section 14.

Build with Next.js App Router + TypeScript. Types come from contracts/openapi.yaml (generate with openapi-typescript). Never decide traffic sequencing in the browser; render backend state only.
Pages: `/` dashboard (all junctions: signals, queues, controller status, mode, phase, emergency badge, failure badge); `/junctions/[id]` detail (desired vs actual signals, queues, mode, alerts, pending commands, transition step with countdown to `deadline_at`, intersection drawing, manual control panel with "manual active until ..." banner and Return to Automatic, emergency banner, failure warnings for the six alert types, recent activity list from /history, simulation form: arrival, clearance, vehicle type, direction, emergency, controller status, ACK, simulator mode).
Data: EventSource on /stream, fall back to polling every 2s after two failures (D-05). Show a "reconnecting" banner when the backend is down.
Errors: handle backend unavailable, request failure, invalid junction (404 page), invalid command (422 message), failed manual override (409 message), failed sensor submission, missing fields. The UI must never crash on partial data.

Self-check loop: run `npm run build` and `npm run lint`; open every state with the backend simulator (SILENT, OFFLINE, emergency) and screenshot or describe each; verify no signal colour is computed in the browser.
Finish with the evidence list from rule 10.
```

### Agent E — QA, Integration and README

```
You own backend/tests/scenarios/, README.md, and the final integration. Read everything: Decision.md, Instruction.md, docs/assessment.pdf.

Phase 1 (parallel with the others): write the 9 scenario scripts from assessment section 15 as executable tests against the HTTP API (pytest + httpx), and a `scripts/demo.sh` that runs them with printed explanations. Write a Postman collection from contracts/openapi.yaml. Draft the README skeleton from section 9 below.
Phase 2 (after all branches are ready): merge in order A, B, C, D. Run `make test-all` and `docker compose up`. Run every scenario. Then do an adversarial review: try to produce two GREENs, a negative queue, a double-counted duplicate, a skipped YELLOW, an unconfirmed command treated as executed, a restart that trusts old state. Every failure goes to MISTAKES.md and back to the owning agent as a clear task (or fixed by you if the owner is done).
Finish the README completely, including the exact section "Assumptions / Questions / Requirement Issues", the "AI / Tool Usage" section (state that Claude was used for architecture/decision support and Antigravity agents for implementation), known limitations, and "what I would do next".
Finish with the evidence list from rule 10.
```

---

## 7. Self-correction protocol

Every agent runs this loop **before** reporting done and **after** every bug fix:

1. **Run** tests, `ruff`, `mypy` (frontend: build + lint). Fix failures first.
2. **Check invariants**: walk the INV list in section 2. For each one, name the test that protects it. No test, no done.
3. **Check decisions**: for every decision your work touches, re-read it and confirm the code matches. Mismatch → fix the code, not the decision.
4. **Attack your own work**: write one new test that tries to break it (property test, odd ordering, double submit).
5. **Log mistakes**: when you find a bug, do not just fix it. Append to `MISTAKES.md`, add a regression test, then re-run step 1.
6. **Stop condition**: two clean full loops in a row.

Templates (Agent 0 creates the files with these headers):

`MISTAKES.md`
```
## M-001 · <short title>
- Agent / date:
- What went wrong:
- Root cause:
- Fix:
- Regression test:
- Decision or invariant involved:
```

`PENDING_DECISIONS.md`
```
## Q-001 · <short title>
- Raised by / date:
- Question:
- Options (with trade-offs):
- Recommendation and why:
- Status: OPEN | APPROVED | REJECTED   (owner fills this in)
### Cross-agent requests
- <agent> needs <file/change> from <agent> because <reason>
```

---

## 8. Scenario → test mapping (assessment section 15)

| # | Scenario | Main checks | Owner of the test |
|---|---|---|---|
| 1 | Normal traffic | Highest-score phase gets served; no needless switching | E (uses A's engine) |
| 2 | Priority traffic | A TRUCK beats an EMPLOYEE_VEHICLE with the same queue size | A + E |
| 3 | Emergency preemption | YELLOW → ALL_RED → GREEN, countdown visible, INV-1..4 | A + E |
| 4 | Manual override | Lease, banner, RETURN_TO_AUTOMATIC, emergency beats manual | A + E |
| 5 | Duplicate event | Second submit returns 200 `duplicate:true`, queue unchanged | B + E |
| 6 | Vehicle clearance | Count goes down once; orphan clear changes nothing | A + B |
| 7 | Controller failure | SILENT → retries → DEGRADED → ALL_RED requested → alert shown | C + E |
| 8 | Restart | Kill backend mid-transition, restart, actual = UNKNOWN, ALL_RED confirmed, history intact | C + E |
| 9 | Concurrent events | The T=0..17ms sequence ends consistent, no double GREEN | C + E |

---

## 9. README skeleton (Agent E fills it in)

1. Overview and architecture diagram (API → application → domain ← infrastructure)
2. Setup and run (`docker compose up`, `make seed`, URLs)
3. API documentation (link to `contracts/openapi.yaml`, Postman collection)
4. Database schema and migrations
5. Traffic-control algorithm (D-09)
6. Traffic-state transitions (section 5.2 as a diagram)
7. Consistency strategy (D-01), recovery (D-20), failure handling (D-19)
8. How to demonstrate each scenario (section 8)
9. Tests: how to run, what they cover
10. **Assumptions / Questions / Requirement Issues** (exact title; copy from `Decision.md` section 4 and add each decision's reasoning)
11. Major architectural decisions (D-01 .. D-06)
12. Known limitations and what to do next (multi-process locking, auth, MQTT adapter, event replay, metrics)
13. **AI / Tool Usage** (Claude for architecture and decision support; Antigravity agents for implementation; you reviewed and can explain the code)

---

## 10. Before you submit (human checklist)

- [ ] `docker compose up` works from a clean clone; seed creates Junction A.
- [ ] `make test-all` is green; run it twice.
- [ ] All 9 scenarios demonstrated by hand through the dashboard at least once.
- [ ] `MISTAKES.md` and `PENDING_DECISIONS.md` have no OPEN items you cannot explain.
- [ ] You can explain, without notes: D-01, D-08, the transition sequence, what happens on ACK timeout, what happens on restart, why emergency does not skip YELLOW.
- [ ] You can change one rule live (for example the starvation limit or emergency timeout) and show the test that covers it.
- [ ] README has the exact section titles required by the assessment.
- [ ] No secrets in the repo; `.env.example` only.
