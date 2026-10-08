# Factory Traffic Management System

A mission-critical, safety-first traffic control and monitoring system designed for industrial intersections operating mixed autonomous, heavy logistics, and human-operated factory traffic. Built according to CSI Smart Tech Assessment V2 requirements, strict hexagonal clean architecture, and formal safety invariants.

---

## 1. Overview and Architecture

The Factory Traffic Management System controls physical and simulated road intersections inside a smart factory. The system coordinates high-frequency vehicle arrivals and departures, prioritizes heavy freight and emergency vehicles, provides bounded manual operator overrides, ensures fail-safe hardware recovery, and streams live intersection telemetry to an industrial monitoring dashboard.

### Hexagonal Architecture

The system strictly enforces a unidirectional Dependency Rule:
```
           ┌──────────────────────────────────────────────┐
           │                 API Layer                    │
           │      FastAPI Routers, Pydantic Schemas       │
           └──────────────────────┬───────────────────────┘
                                  │ (commands & events)
                                  ▼
           ┌──────────────────────────────────────────────┐
           │              Application Layer               │
           │ JunctionWorker (Actor/Queue), Ticker,        │
           │ EffectExecutor, CommandTracker, Recovery     │
           └──────────────┬───────────────────────────────┘
                          │                      │
     (domain models)      ▼                      ▼      (uses ports)
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│           Domain Layer           │   │       Infrastructure Layer       │
│ Pure Traffic Engine, Scoring,    │◄──┤ Async Repositories (PostgreSQL), │
│ Config Validation, Safety Rules  │   │ REST Simulator, Hardware Ports   │
│ (Zero I/O, Pure Functions)       │   │                                  │
└──────────────────────────────────┘   └──────────────────────────────────┘
```

- **Domain Layer (`backend/app/domain/`):** Pure deterministic traffic state machine (`(state, event, now) -> (new_state, effects)`). Free from database queries, network I/O, system clock reads (`datetime.now()`), or random numbers. Governed by 9 core safety invariants (INV-1 through INV-9).
- **Application Layer (`backend/app/application/`):** Orchestrates concurrency, per-junction serialized actor queues (D-01), periodic tick loops (P-03), transaction execution, ACK tracking, and recovery sequences.
- **Infrastructure Layer (`backend/app/infrastructure/`):** Implements persistence via PostgreSQL 16 (SQLAlchemy 2 async + Alembic), hardware controller adapters (REST simulator with AUTO_ACK, DELAYED, SILENT, and OFFLINE modes), and event sinks.
- **API Layer (`backend/app/api/`):** Thin HTTP/SSE translation layer mapping REST requests to junction actor events, validating payloads against OpenAPI schemas, and returning standardized error envelopes.
- **Frontend (`frontend/`):** Next.js 14 App Router, TypeScript, Tailwind CSS, Server-Sent Events (SSE) with 2-second polling fallback (D-05), and interactive SVG intersection diagrams.

---

## 2. Setup and Run

### Prerequisites
- Docker & Docker Compose (v2.20+)
- Python 3.12+ (for local backend development)
- Node.js 20+ & npm (for local frontend development)

### Quick Start with Docker Compose
Clone the repository and run all services:
```bash
# 1. Start database, backend, and frontend
docker compose up -d

# 2. Verify containers are healthy
docker compose ps

# 3. Seed initial Junction A configuration
docker compose exec backend python -m app.seed
```

### Service URLs
- **Web Dashboard & Live Controls:** [http://localhost:3000](http://localhost:3000)
- **Junction Detail View:** [http://localhost:3000/junctions/A](http://localhost:3000/junctions/A)
- **Backend API Root:** [http://localhost:8000](http://localhost:8000)
- **Interactive OpenAPI Docs (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **OpenAPI Schema Specification:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

### Local Development Setup (Without Docker)
```bash
# Backend setup
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000

# Frontend setup (in a separate terminal)
cd frontend
npm install
npm run dev  # Runs on http://localhost:3000
```

---

## 3. API Documentation

The complete API contract is frozen and published in:
- **OpenAPI 3.1 Specification:** [`contracts/openapi.yaml`](file:///f:/Programming/factory-traffic/contracts/openapi.yaml)
- **Postman Collection v2.1.0:** [`contracts/postman_collection.json`](file:///f:/Programming/factory-traffic/contracts/postman_collection.json)

### Core Endpoints Summary

| Method | Path | Purpose | Success Code | Error Codes |
|---|---|---|---|---|
| `GET` | `/api/junctions` | List all configured junctions | `200 OK` | - |
| `POST` | `/api/junctions` | Create new junction configuration (validated D-10) | `201 Created` | `409 Conflict`, `422 Unprocessable` |
| `GET` | `/api/junctions/{id}` | Get junction metadata & configuration | `200 OK` | `404 Not Found` |
| `GET` | `/api/junctions/{id}/status` | Get live junction state (desired/actual, queues, transition, alerts) | `200 OK` | `404 Not Found` |
| `GET` | `/api/junctions/{id}/stream` | Server-Sent Events (SSE) live status stream | `200 OK` | `404 Not Found` |
| `GET` | `/api/junctions/{id}/history` | Paginated append-only audit trail (`limit`, `before_id`, `event_type`) | `200 OK` | `404 Not Found` |
| `POST` | `/api/sensor-events` | Ingest vehicle detection event (`ARRIVED` / `CLEARED`) | `201 Applied`, `200 Duplicate`, `202 Not Applied` | `404 Not Found`, `422 Unprocessable` |
| `POST` | `/api/junctions/{id}/commands` | Issue operator command (`MANUAL_GREEN_REQUEST`, `RETURN_TO_AUTOMATIC`) | `202 Accepted` | `404 Not Found`, `409 Conflict`, `422 Unprocessable` |
| `POST` | `/api/controller-events` | Ingest hardware signal controller responses (`ACK` / `NACK`) | `200 OK` | `404 Not Found`, `422 Unprocessable` |
| `POST` | `/api/device-status` | Report sensor or controller health telemetry | `200 OK` | `404 Not Found`, `422 Unprocessable` |
| `POST` | `/api/simulator/{id}/mode` | Switch controller simulator mode (`AUTO_ACK`, `DELAYED`, `SILENT`, `OFFLINE`) | `200 OK` | `404 Not Found`, `422 Unprocessable` |

### Standardized Error Envelope
All error responses adhere to the unified format across all routes:
```json
{
  "error": {
    "code": "JUNCTION_DEGRADED",
    "message": "Signal controller offline; manual commands rejected.",
    "details": {}
  }
}
```

---

## 4. Database Schema and Migrations

The relational model consists of 8 tables managed via Alembic migrations ([`backend/alembic/versions/001_initial_schema.py`](file:///f:/Programming/factory-traffic/backend/alembic/versions/001_initial_schema.py)), matching [`contracts/schema.sql`](file:///f:/Programming/factory-traffic/contracts/schema.sql):

1. **`junctions`**: Junction metadata, names, non-conflicting phase definitions, and timing profiles.
2. **`junction_state`**: Durable single-row snapshot per junction (`version`, `mode`, `serving`, `step`, `target`, `deadline_at`, `desired`, `actual`, `manual`, `emergencies`, `updated_at`).
3. **`vehicles`**: Vehicle arrival and clearance lifecycle tracking. Includes a partial unique index on `(junction_id, vehicle_id) WHERE status = 'WAITING'` to guarantee at most one waiting entry per vehicle.
4. **`processed_events`**: Idempotency log for sensor and device events. Duplicate event submissions return `200 OK` with `duplicate: true` without reprocessing.
5. **`direction_sequence`**: Monotonic sequence counters per `(junction_id, direction)` to detect out-of-order sensor packets (D-11).
6. **`commands`**: Outstanding and historical hardware signal commands (`command_id`, `requested_state`, `status`, `attempts`, `deadline_at`, `actual_state`).
7. **`device_status`**: Current health status of inductive sensors and physical controllers (`ONLINE`, `OFFLINE`, `DEGRADED`, `WARNING`, `UNKNOWN`).
8. **`audit_log`**: Strictly append-only compliance ledger recording every state change, command issuance, manual override, and preemption. Code contains zero `UPDATE` or `DELETE` statements targeting this table.

---

## 5. Traffic-Control Algorithm

The dynamic scheduling algorithm ([`backend/app/domain/scoring.py`](file:///f:/Programming/factory-traffic/backend/app/domain/scoring.py), Decision D-09) balances logistics throughput, vehicle weight priorities, and starvation prevention:

### Phase Priority Formula
For each candidate phase $P$, the priority score $S(P)$ is computed as:
$$S(P) = \sum_{v \in \text{Waiting}(P)} W(v.\text{type}) + \sum_{d \in \text{Directions}(P)} \min\left(\text{wait\_seconds}(d), \text{starvation\_after}\right)$$

### Vehicle Weight Classes (Decision D-14)
- **`TRUCK` (Weight = 3):** Heavy logistics and raw material transports have the highest operational priority.
- **`FORKLIFT` (Weight = 2):** Intermediate internal factory transport.
- **`EMPLOYEE_VEHICLE` (Weight = 1):** Standard commuter traffic.
- **`EMERGENCY` (Weight = 0 / Preemption):** Ambulances and fire engines bypass numerical scoring entirely, triggering immediate preemption (Decision D-15).

### Timing Constraints & Anti-Flapping
- **Minimum Green Hold (`min_green` = 10s default):** Signals will not transition away from the current phase until `min_green` duration has elapsed, preventing dangerous rapid oscillation.
- **Maximum Green Limit (`max_green` = 60s default):** Prevents heavy traffic on one approach from permanently starving competing approaches.
- **Starvation Ceiling (`starvation_after` = 90s default):** Waiting vehicles accrue additional points per second waited until `starvation_after`, guaranteeing bounded maximum delay even for single employee vehicles.
- **No Idle Flapping:** When all queues are empty, the junction remains on the current phase without cycling green across empty approaches.

---

## 6. Traffic-State Transitions

The state machine implements a deterministic multi-step clearance sequence ([`backend/app/domain/engine.py`](file:///f:/Programming/factory-traffic/backend/app/domain/engine.py), Section 5.2). GREEN is never granted immediately upon switching.

```
                  ┌──────────────────────────────┐
                  │          Step: BOOT          │
                  │   All Desired: RED           │
                  │   All Actual: UNKNOWN        │
                  └──────────────┬───────────────┘
                                 │ Fail-safe ALL_RED confirmed by ACK
                                 ▼
                  ┌──────────────────────────────┐
                  │         Step: GREEN          │
                  │ Serving Phase: GREEN (Desired│
                  │ and Actual confirmed)        │
                  └──────────────┬───────────────┘
                                 │ Preemption / Higher Score / Max Green
                                 ▼
                  ┌──────────────────────────────┐
                  │         Step: YELLOW         │
                  │ Serving Phase: YELLOW        │
                  │ Controller must ACK YELLOW   │
                  │ Duration: yellow_duration    │
                  └──────────────┬───────────────┘
                                 │ Yellow duration elapses & ACK confirmed
                                 ▼
                  ┌──────────────────────────────┐
                  │        Step: ALL_RED         │
                  │ All Directions: RED          │
                  │ Controller must ACK RED      │
                  │ Duration: all_red_duration   │
                  └──────────────┬───────────────┘
                                 │ Safe clearance complete & ACK confirmed
                                 ▼
                  ┌──────────────────────────────┐
                  │         Step: GREEN          │
                  │ Target Phase: GREEN          │
                  │ Controller must ACK GREEN    │
                  └──────────────────────────────┘
```

### Safety Invariants Enforced
- **INV-1:** Conflicting directions (e.g. NORTH and EAST) are NEVER GREEN simultaneously in `desired` or `actual`.
- **INV-2:** YELLOW is NEVER skipped when terminating GREEN (minimum safe stopping distance).
- **INV-3:** ALL_RED safe clearance interval (default 2s) is ALWAYS enforced before granting conflicting GREEN.
- **INV-4:** Desired signal state is decoupled from Actual signal state. Desired reflects software intent; Actual reflects hardware sensor confirmation.

---

## 7. Consistency, Recovery, and Failure Handling

### Consistency Strategy (Decision D-01)
To eliminate database race conditions and split-brain states:
- Each junction is managed by exactly **one active in-memory actor** (`JunctionWorker`) backed by an `asyncio.Queue`.
- Inbound HTTP requests submit events to the worker's queue and await an `asyncio.Future`.
- Events are processed in strict serialization order. Concurrent events arriving within milliseconds (e.g. assessment scenario 9) are sequenced deterministically.
- State mutation, pending command registration, audit log generation, and event idempotency logging commit in a **single database transaction** before hardware commands are transmitted.

### Failure Handling & Command Tracking (Decision D-19)
- Physical controller commands must be acknowledged within `ack_timeout` (default 3s).
- If no ACK is received, the system retries up to `max_retries` (default 2, 3 total attempts) using the **same idempotent `command_id`**.
- If all attempts expire without ACK, the junction enters **`DEGRADED`** mode:
  - Software marks all `actual` signal states as `UNKNOWN`.
  - The engine commands fail-safe **`ALL_RED`** to the controller.
  - A high-priority system alert `CONTROLLER_OFFLINE` / `SIGNAL_FAILURE` is raised.
  - The dashboard displays a prominent banner: *"Manual traffic marshal required"*.
  - Manual override commands are rejected with `409 Conflict`.

### Boot & Restart Recovery (Decision D-20)
If the backend process crashes or restarts:
- On startup, the recovery routine loads the last persisted junction state.
- Physical lamps may have changed while the server was offline; therefore, `actual` signals are immediately reset to **`UNKNOWN`** (INV-8).
- Any pending unconfirmed commands are marked `ABANDONED`.
- The engine issues a mandatory fail-safe `ALL_RED` command and awaits confirmation before entering `AUTOMATIC` scheduling.
- Active manual override leases (if still unexpired) and waiting emergency vehicles are safely re-derived from persistent storage.

---

## 8. How to Demonstrate Each Scenario

An automated demonstration script is provided in [`scripts/demo.sh`](file:///f:/Programming/factory-traffic/scripts/demo.sh) and [`scripts/demo.py`](file:///f:/Programming/factory-traffic/scripts/demo.py). It can run against the live docker stack or standalone in-process:

```bash
# Run all 9 scenarios against live server (http://localhost:8000)
./scripts/demo.sh

# Or run a specific scenario (e.g. Scenario 3: Emergency Preemption)
python scripts/demo.py --scenario 3

# Or run standalone in-process (zero external dependencies)
python scripts/demo.py --standalone
```

### Scenario Breakdown

#### Scenario 1: Normal Traffic (Score-based switching)
- **Input:** 2 TRUCKs arrive on EAST while NS is GREEN.
- **Verification:** Score on EW exceeds NS; after `min_green` elapses, system steps through YELLOW -> ALL_RED -> GREEN on EW.
- **Decisions:** D-08, D-09.

#### Scenario 2: Priority Traffic (TRUCK beats EMPLOYEE_VEHICLE)
- **Input:** 1 TRUCK arrives on NORTH (weight 3); 1 EMPLOYEE_VEHICLE arrives on EAST (weight 1). Both queues have count 1.
- **Verification:** Scoring assigns NS score 3 and EW score 1. NS is prioritized.
- **Decisions:** D-09, D-14.

#### Scenario 3: Emergency Preemption
- **Input:** Vehicle type `EMERGENCY` arrives on WEST while NS is serving GREEN.
- **Verification:** Mode switches immediately to `EMERGENCY`. Preemption starts instantly: current green transitions to YELLOW -> ALL_RED -> GREEN for WEST. Transition countdown is rendered on UI.
- **Decisions:** D-15, S-1, INV-1..4.

#### Scenario 4: Manual Override & Lease Expiration
- **Input:** Operator issues `MANUAL_GREEN_REQUEST` for EAST (`issued_by: "dispatcher-1"`). Later, an `EMERGENCY` vehicle arrives.
- **Verification:** Mode becomes `MANUAL` with active countdown lease (300s). When the emergency vehicle arrives, manual mode is immediately terminated per Decision D-15.
- **Decisions:** D-15, D-18.

#### Scenario 5: Duplicate Sensor Event
- **Input:** Ingest identical arrival event (`event_id: "evt-dup-1"`) twice.
- **Verification:** 1st call returns `201 Created` with `status: "APPLIED"`. 2nd call returns `200 OK` with `status: "DUPLICATE"` and `duplicate: true`. Queue count increments exactly once.
- **Decisions:** D-11, P-02.

#### Scenario 6: Vehicle Clearance & Orphan Handling
- **Input:** Vehicle `VH-1` arrives then clears. Later, a clearance event arrives for an unknown vehicle `VH-GHOST`.
- **Verification:** Queue decrements back to 0. Orphan clearance returns `202 Accepted` with `status: "NOT_APPLIED"`. Queue count remains 0, never negative (INV-5).
- **Decisions:** D-13, P-01, INV-5.

#### Scenario 7: Controller Failure & Degraded Mode
- **Input:** Set simulator mode to `OFFLINE` or `SILENT`.
- **Verification:** After retries exhaust, junction transitions to `DEGRADED`. Actual states become `UNKNOWN`, fail-safe `ALL_RED` is commanded, and `CONTROLLER_OFFLINE` alert is triggered.
- **Decisions:** D-19, INV-6, INV-7.

#### Scenario 8: Restart Recovery
- **Input:** Simulate server crash mid-transition and reboot.
- **Verification:** System sets `actual` to `UNKNOWN`, commands `ALL_RED`, and preserves full append-only audit trail in PostgreSQL.
- **Decisions:** D-20, INV-8, INV-9.

#### Scenario 9: Concurrent Events (T=0..17ms Sequence)
- **Input:** Rapid burst of simultaneous events via `asyncio.gather`: T=0 TRUCK N, T=4ms EMERGENCY E, T=8ms MANUAL W, T=12ms Duplicate EMERGENCY E.
- **Verification:** Serialized actor queue processes events without race conditions; emergency preemption safely prevails; duplicate is filtered; no conflicting greens ever occur.
- **Decisions:** D-01, INV-1..4.

---

## 9. Tests and Test Coverage

The test suite covers domain logic, invariant property testing (Hypothesis), database repositories, HTTP API routers, runtime workers, and complete end-to-end scenarios.

### Running Test Suite
```bash
# Run entire test suite (64 tests across all layers)
pytest backend/tests/

# Run domain unit & property-based invariant tests
pytest backend/tests/domain/

# Run end-to-end scenario integration tests
pytest backend/tests/scenarios/

# Run static code analysis & type checking
ruff check backend/
mypy backend/

# Run frontend linting & production build check
cd frontend
npm run lint
npm run build
```

### Test Suite Structure
- **`backend/tests/domain/` (33 tests):**
  - Unit tests for every architectural decision (D-07 through D-20).
  - Hypothesis property tests verifying safety invariants INV-1 through INV-9 across randomized permutations of arrivals, clears, commands, and controller ACKs.
- **`backend/tests/api/` (17 tests):**
  - Asynchronous repository testing (CRUD, partial indexes, append-only audit enforcement).
  - FastAPI router status code verification (201, 200, 202, 404, 409, 422).
  - SSE event streaming and heartbeat ping emission.
- **`backend/tests/application/` (5 tests):**
  - Worker serialization under heavy asynchronous load.
  - RestSimulator controller mode switching (AUTO_ACK, DELAYED, SILENT, OFFLINE).
  - Boot recovery orchestration and crash handling.
- **`backend/tests/scenarios/test_scenarios.py` (9 tests):**
  - Full end-to-end verification of all 9 CSI assessment scenarios.

---

## 10. Assumptions / Questions / Requirement Issues

During system design and architecture reviews (recorded in `Decision.md`), nine specific ambiguities in the assessment specification were identified and resolved:

| # | Specification Issue | System Handling | Rationale & Architectural Reference |
|---|---|---|---|
| **S-1** | *"Immediately begin"* emergency preemption conflicts with required yellow clearance (5s) and all-red clearance (2s). Granting green in under 7s would cause physical collisions with vehicles already in the intersection. | The transition sequence begins **immediately** (current green is terminated without waiting for timer expiry), but the physical lamps still safely cycle through YELLOW and ALL_RED before granting GREEN to the emergency approach. | Safety Invariants INV-1, INV-2, and INV-3 take precedence over immediate green. The dashboard displays an active countdown indicating preemption in progress (Decision D-15). |
| **S-2** | Sensor event `sequence_no` specification does not identify which sensor generated it, leaving counter scope ambiguous. | `sequence_no` is strictly scoped per `(junction_id, direction)`. | Monotonic sequence counters are maintained per approach direction in the `direction_sequence` table (Decision D-11). |
| **S-3** | `VEHICLE_CLEARED` event payload lacks `vehicle_type`, which is needed to decrement weighted queue scores. | Vehicle type is resolved by looking up the active `WAITING` record by `vehicle_id`. If no arrival record exists, an orphan clearance marker is stored. | Prevents corrupted queue weights. If an orphan clear arrives, it is recorded and returns `202 Accepted` with `NOT_APPLIED` without decrementing counts (Decisions D-13, P-01). |
| **S-4** | `POST /api/junctions` endpoint could be invoked with conflicting phase definitions (e.g. sharing directional approaches across phases). | Strict domain configuration validator rejects overlapping approaches across phases with `422 Unprocessable Entity`. | Conflicting approaches within a single phase would violate mutual exclusion (Decision D-10). |
| **S-5** | Assessment scenario text mentions *"material-carrying vehicles"*, but the schema enum defines only four vehicle types. | Unsupported types are rejected with `422 Unprocessable Entity` (`INVALID_VEHICLE_TYPE`). Supported types: `EMERGENCY`, `TRUCK`, `FORKLIFT`, `EMPLOYEE_VEHICLE`. | Unvalidated vehicle types would corrupt prioritization math (Decision D-14). |
| **S-6** | The specification omitted the duration for the `ALL_RED` safe clearance step. | Defaulted to 2.0s, configurable in `TimingsConfig.all_red`. | Standard traffic engineering safety clearance interval (Decision D-07). |
| **S-7** | The assessment document provided an example device health status JSON payload, but specified no HTTP endpoint. | Added `POST /api/device-status` matching the payload structure. | Provides a standardized ingress for sensor and controller telemetry (Decision P-02). |
| **S-8** | Specification does not include authentication, but manual traffic override is safety-critical. | Added mandatory `issued_by` audit attribute in command requests; documented production requirement for OAuth2/RBAC. | Captures operator attribution in the append-only audit trail while maintaining assessment compatibility (Decision D-18). |
| **S-9** | Signal states are restricted to `RED`, `YELLOW`, `GREEN`: no flashing yellow or flashing red error aspect exists. | When the controller fails, the system transitions to `DEGRADED`, commands `ALL_RED`, and requires an on-site human traffic marshal. | A solid RED fail-safe prevents uncoordinated entry into the intersection (Decision D-19). |

---

## 11. Major Architectural Decisions

Detailed rationale is logged in [`Decision.md`](file:///f:/Programming/factory-traffic/Decision.md):

- **D-01 (Serialized Actor per Junction):** Each junction is owned by exactly one `JunctionWorker` with an `asyncio.Queue`. Eliminates distributed locking overhead, eliminates SQLite/Postgres write conflicts, and guarantees total ordering of concurrent sensor events.
- **D-02 (Decoupled Desired vs Actual Signals):** The state machine distinguishes software intent (`desired`) from confirmed hardware lamp state (`actual`). Desired is updated when commands are issued; Actual is updated only when the controller returns an ACK.
- **D-03 (Partial Unique Index for Waiting Vehicles):** PostgreSQL partial unique index `(junction_id, vehicle_id) WHERE status = 'WAITING'` guarantees a vehicle cannot be double-queued while in transit.
- **D-04 (Pluggable Controller Port):** Application logic depends exclusively on the `ControllerPort` abstract interface. Enables seamless switching between `RestSimulatorController` (with live failure modes) and production hardware protocols like MQTT or Modbus.
- **D-05 (Resilient SSE Stream with Polling Fallback):** The Next.js frontend connects via EventSource to `/api/junctions/{id}/stream`. If two consecutive connection drops occur, it seamlessly falls back to 2-second HTTP polling.
- **D-06 (Strictly Append-Only Audit Trail):** Every state change, operator command, ACK, timeout, and preemption appends to `audit_log`. Updates and deletes are prohibited by database schema design.

---

## 12. Known Limitations and What to Do Next

1. **Multi-Node Horizontal Scaling:** The current actor-per-junction architecture runs in a single backend process. To scale horizontally across multiple container instances, workers should use Redis Streams or PostgreSQL advisory locks (`pg_try_advisory_xact_lock`) for leader election per junction.
2. **Authentication & Authorization:** The current API accepts `issued_by` as an untrusted string. Production deployments require JWT/OIDC authentication with role-based access control (RBAC) restricting manual overrides to certified dispatchers.
3. **Industrial MQTT / Modbus Adapter:** While the `ControllerPort` abstraction is complete, a native MQTT broker connector with TLS and QoS 1 should be deployed to interface with physical Siemens or Allen-Bradley PLCs.
4. **Time-Series Telemetry & Prometheus Metrics:** Add Prometheus metrics instrumentation (`http_requests_total`, `phase_duration_seconds`, `queue_wait_seconds_bucket`) and OpenTelemetry tracing across event ingestion pipelines.
5. **Event Sourcing & Replay Engine:** Store raw sensor payloads in an append-only event stream (Kafka or EventStore) to enable historical deterministic intersection re-simulations for incident investigations.

---

## 13. AI / Tool Usage

In accordance with assessment integrity and transparency standards:
- **Claude (Anthropic):** Used for initial high-level architectural trade-off analysis, invariant formalization (INV-1 through INV-9), and scaffolding the decision review log (`Decision.md`).
- **Antigravity (Google DeepMind):** Used as the primary agentic pair-programming assistant to implement domain engine transitions, Alembic database migrations, FastAPI endpoints, Next.js dashboard UI, scenario test suites, and documentation.
- **Human Review & Accountability:** All architectural choices, database schemas, state transition algorithms, and test assertions were reviewed, tested against real executions, and verified to satisfy every specification invariant.