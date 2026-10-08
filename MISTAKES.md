# MISTAKES.md — Factory Traffic Management System

This file logs bugs found and fixed during development, per the self-correction protocol (Instruction.md section 7).

## Template
```markdown
## M-xxx · <short title>
- Agent / date:
- What went wrong:
- Root cause:
- Fix:
- Regression test:
- Decision or invariant involved:
```

---

## M-001 · Hardcoded backend.app import prefix broke Docker container and backend directory execution
- Agent / date: Scaffold Reviewer / 2026-10-08
- What went wrong: All backend modules and tests imported using `from backend.app...` instead of `from app...`. In Docker (where `WORKDIR /app` contains `app/`), `uvicorn app.main:app` crashed with `ModuleNotFoundError: No module named 'backend'`. Running `pytest` inside `backend/` also failed with `ModuleNotFoundError: No module named 'backend'`.
- Root cause: Modules assumed execution exclusively from root workspace with root on `sys.path`, neglecting that the Python project root is `backend/` and `app` is the packaged top-level module.
- Fix: Normalized all internal imports to `from app...`, configured `pythonpath = ["."]` in `backend/pyproject.toml`, and configured `mypy_path = ["backend", "."]` so that execution succeeds both from repo root and within `backend/` or Docker.
- Regression test: Verified `uvicorn app.main:app` module import from `backend/` and `pytest tests/domain/test_engine.py` from `backend/`.
- Decision or invariant involved: D-00, D-06.

## M-002 · Missing .eslintrc.json blocked frontend lint
- Agent / date: Scaffold Reviewer / 2026-10-08
- What went wrong: Running `next lint` hung prompting interactively for ESLint configuration and failed.
- Root cause: `.eslintrc.json` was missing despite `eslint-config-next` being in `devDependencies`.
- Fix: Added `frontend/.eslintrc.json` extending `next/core-web-vitals`.
- Regression test: `npm run lint` now passes non-interactively with 0 errors/warnings.
- Decision or invariant involved: D-00.

## M-003 · Relative alembic script_location and missing versions directory failed migrations
- Agent / date: Scaffold Reviewer / 2026-10-08
- What went wrong: `alembic -c backend/alembic.ini heads` failed with `Path doesn't exist: alembic`.
- Root cause: `backend/alembic.ini` had relative `script_location = alembic` which only worked if CWD was `backend/`, and `backend/alembic/versions` directory was absent.
- Fix: Changed `script_location = %(here)s/alembic`, `prepend_sys_path = %(here)s/..`, and created `backend/alembic/versions/.gitkeep`.
- Regression test: `alembic -c backend/alembic.ini heads` succeeds from both root and `backend/`.
- Decision or invariant involved: D-06.

## M-004 · Nullable primary key column in device_status table
- Agent / date: Scaffold Reviewer / 2026-10-08
- What went wrong: `device_status` DDL declared `direction VARCHAR(16)` as part of `PRIMARY KEY (junction_id, device_type, direction)`, and SQLAlchemy model declared `direction: Mapped[str | None] = mapped_column(primary_key=True)`. In SQL/PostgreSQL, primary key columns cannot be NULL; storing junction-wide controller status (`direction=None`) would trigger `NOT NULL` constraint violation.
- Root cause: Misalignment between SQL PK constraints and nullable device direction.
- Fix: In `contracts/schema.sql` and `models.py`, set `direction VARCHAR(16) NOT NULL DEFAULT ''` so that controller status uses empty string for direction.
- Regression test: Verified SQLAlchemy table metadata creation and mypy type checks.
- Decision or invariant involved: D-06, P-02.

## M-005 · Missing seed script caused make seed to fail
- Agent / date: Scaffold Reviewer / 2026-10-08
- What went wrong: `Makefile` defined `seed: python -m backend.app.seed`, but `backend/app/seed.py` did not exist.
- Root cause: Agent 0 omitted the seed script file mentioned in the Makefile and Instruction.md.
- Fix: Created `backend/app/seed.py` with `seed_junction_a()` using default config and initial state, plus loop policy handling for Windows.
- Regression test: Verified `py -m app.seed` imports and executes with graceful connection fallback.
- Decision or invariant involved: Instruction.md 6, 10.


## M-006 · Domain engine process_event Phase 0 stub failed emergency preemption
- Agent / date: Agent A (Domain Engine) / 2026-10-08
- What went wrong: `backend/tests/domain/test_engine.py::test_emergency_preemption_initiates_yellow_transition` failed with `AssertionError: assert <Step.GREEN: 'GREEN'> == <Step.YELLOW: 'YELLOW'>`.
- Root cause: `backend/app/domain/engine.py` was a Phase 0 stub returning `state, []` without implementing the state machine and transition sequence defined in Instruction.md section 5.2.
- Fix: Implemented pure domain traffic engine state machine in `engine.py`, scoring algorithm in `scoring.py` (D-09), and config validation in `config.py` (D-10). When a `VehicleArrived` event with `vehicle_type=VehicleType.EMERGENCY` on a conflicting phase arrives during `Step.GREEN`, the engine immediately initiates safe preemption: sets `step=Step.YELLOW`, `target=Phase.EW`, `desired` to `YELLOW` for serving directions, and emits `SendSignalCommand` with `requested_state=Signal.YELLOW`.
- Regression test: `backend/tests/domain/test_engine.py::test_regression_emergency_preemption_original_bug` and `backend/tests/domain/test_engine.py::test_emergency_preemption_initiates_yellow_transition`.
- Decision or invariant involved: D-02, D-08, D-15, D-16, D-17, INV-1, INV-2, INV-3, INV-4, Instruction.md section 5.2.

## M-007 · State machine deadlocks, D-16 FCFS violation, unrecoverable DEGRADED mode, and stale targets
- Agent / date: Agent A (Domain Engine Reviewer) / 2026-10-08
- What went wrong:
  1. In `Step.ALL_RED`, when GREEN commands were already emitted for target phase T, incoming emergency or manual commands overwrote `target`, causing subsequent controller ACKs to be unmatched, permanently deadlocking the state machine in `Step.ALL_RED` while physical signals were GREEN in the field and violating INV-1 on subsequent cycles.
  2. In competing emergencies, later emergencies arriving during `Step.YELLOW` or `Step.ALL_RED` overwrote `target`, violating Decision D-16 First-Come-First-Served.
  3. When emergency preemption occurred during manual control, `manual.active` remained `True`, allowing the junction to inherit the old manual override after emergency clearance in violation of Decision D-15.
  4. `ControllerNack` left `actual` signal states marked `Signal.GREEN` rather than `Signal.UNKNOWN`, violating Decision D-19 and Invariant INV-7.
  5. Junction had no mechanism to recover from `Mode.DEGRADED` upon controller reconnect, remaining stuck in DEGRADED indefinitely.
  6. On restart (`Boot`), stale transition `target` from before crash was preserved, bypassing re-derived emergency preemption and queue scheduling (Decision D-20).
  7. In `Mode.DEGRADED`, `RETURN_TO_AUTOMATIC` was rejected with `COMMAND_REJECTED` instead of being accepted per Decision P-04.
- Root cause: Missing state machine guards in `engine.py` against mutating target when commands are committed to hardware; blind target overwrite on incoming emergency events; omission of manual deactivation; omission of actual=UNKNOWN reset on NACK; lack of reconnect restart flow; and missing target clearance on Boot.
- Fix:
  1. Prevented target overwriting when GREEN commands are in flight in `Step.ALL_RED`, queueing emergencies for immediate safe preemption upon GREEN confirmation.
  2. Enforced D-16 FCFS by targeting the primary emergency phase (`emergencies[0].phase`).
  3. Deactivated manual override upon emergency preemption and upon returning to AUTOMATIC per D-15.
  4. Set all actual signals to `Signal.UNKNOWN` on `ControllerNack` and cleared pending commands.
  5. Implemented controller reconnect recovery in `DeviceStatusChanged` (initiates ALL_RED confirmation, restores mode to AUTOMATIC/EMERGENCY, and clears failure alerts upon all-red confirmation).
  6. Reset `target = None` on `Boot`.
  7. Accepted `RETURN_TO_AUTOMATIC` in `Mode.DEGRADED` without physical signal changes per P-04.
- Regression test: `backend/tests/domain/test_engine.py::test_regression_emergency_during_all_red_with_green_commanded_no_deadlock`, `test_regression_d16_fcfs_competing_emergencies_arrival_order`, `test_regression_d15_emergency_terminates_manual_no_revival`, `test_regression_d19_controller_nack_sets_actual_unknown`, `test_regression_d19_controller_reconnect_recovers_to_automatic`, `test_regression_d20_restart_mid_transition_clears_target`, `test_regression_p04_return_to_automatic_accepted_in_degraded`, `test_d14_unknown_vehicle_types_rejected`, `test_repeated_emergency_event_does_not_duplicate_or_retrigger`, `test_ack_never_arrives_holds_transition_safely`.
- Decision or invariant involved: D-08, D-14, D-15, D-16, D-17, D-18, D-19, D-20, P-04, INV-1, INV-2, INV-3, INV-4, INV-7, INV-8, INV-9.

## M-008 · CommandTracker attempt counter reset on retry prevented degradation to DEGRADED
- Agent / date: Agent C (Runtime, Controller, Recovery) / 2026-10-08
- What went wrong: When controller commands were retried on timeout in `junction_worker.py`, `command_tracker.record_command_sent` was called post-commit, which unconditionally re-instantiated `TrackedCommand(..., attempts=1)`, resetting the attempt count back to 1 and preventing the junction from ever reaching `max_retries` and degrading to `Mode.DEGRADED`. In addition, `CommandRepository.record_command` raised duplicate key constraint errors when recording retried commands.
- Root cause: `CommandTracker.record_command_sent` did not check if the command was already tracked before creating a fresh `TrackedCommand`, and `CommandRepository.record_command` did not handle existing command rows.
- Fix:
  1. Updated `CommandTracker.record_command_sent` to preserve and return the existing `TrackedCommand` if `command_id` is already present.
  2. Updated `CommandRepository.record_command` to update `attempts`, `sent_at`, and `deadline_at` on duplicate command ID rather than failing with duplicate key error.
- Regression test: `backend/tests/application/test_application.py::test_silent_controller_leads_to_degraded_after_retries`.
- Decision or invariant involved: D-19, INV-7, P-04.


## M-009 · Boot recovery discarded persistent waiting vehicles, active manual leases, and failed to record controller NACKs in DB
- Agent / date: Agent B/Reviewer / 2026-10-08
- What went wrong:
  1. In `backend/app/application/recovery.py`, `state_model` and `waiting` were queried from the database on reboot, logged via `logger.info`, but never assigned back to `worker.state`. This caused `worker.state.waiting_vehicles` to remain empty, wiped active manual leases, and caused the domain `Boot` event to find 0 emergency vehicles, silently clearing emergency mode and reporting all queue counts as 0 after restart in violation of `D-20` and `INV-8`.
  2. `recovery.py` omitted calling `worker.command_tracker.abandon_all()`, leaving stale in-flight commands tracked across process restart.
  3. In `backend/app/application/junction_worker.py`, incoming `ControllerNack` events were not validated against `command_tracker` or the database, returning 200 instead of 404 for unknown command IDs.
  4. NACKed or timed-out commands were never transitioned to `status = "FAILED"` in `CommandRepository` / database (`CommandRepository` lacked a `record_failed` method).
  5. In `backend/app/api/routers.py`, `_get_worker_or_404` started a worker for newly registered junctions found in the database without calling `recover_junction`, leading to unrecovered state if loaded dynamically.
  6. In `junction_worker.py`, `get_status_dict()` hardcoded `stale_queues = []` and omitted sensor device statuses.
  7. Scenario 8 tests in `test_scenarios.py` and `demo.py` were superficial—only checking `actual == UNKNOWN` without asserting queue retention or emergency state preservation across reboot.
- Root cause: Partial implementation of `recover_junction` where DB fetch was executed for logging only without populating in-memory domain state; missing `FAILED` state transitions in repository; and missing dynamic worker recovery hook.
- Fix:
  1. Updated `recovery.py` to restore `version`, `mode`, `serving`, `manual` lease, and deserialize `WaitingVehicle` domain objects into `worker.state.waiting_vehicles` before emitting `Boot`, and invoked `worker.command_tracker.abandon_all()`.
  2. Added `record_failed(command_id)` in `CommandRepository` to transition commands to `FAILED` in the database.
  3. Added command validation in `junction_worker.py` for `ControllerNack` to reject unknown command IDs with 404, mark commands failed in `command_tracker` and database upon NACK or timeout past `max_retries`.
  4. Updated `_get_worker_or_404` to run `recover_junction` when dynamically instantiating workers from DB.
  5. Added dynamic `stale_queues` tracking based on offline sensor device statuses in `junction_worker.py`.
  6. Upgraded Scenario 8 in `test_scenarios.py` and `scripts/demo.py` to ingest vehicles prior to reboot and assert persistent queue retention alongside `INV-8`.
- Regression test:
  - `backend/tests/application/test_application.py::test_regression_boot_recovery_restores_waiting_vehicles_and_emergency_mode`
  - `backend/tests/application/test_application.py::test_regression_boot_recovery_restores_manual_lease`
  - `backend/tests/application/test_application.py::test_regression_controller_nack_marks_command_failed_in_db_and_rejects_unknown`
  - `backend/tests/application/test_application.py::test_regression_sensor_offline_reports_stale_queues_and_device_status`
  - `backend/tests/scenarios/test_scenarios.py::test_scenario_8_restart_recovery`
  - `scripts/demo.py` (Scenario 8)
- Decision or invariant involved: D-19, D-20, P-02, INV-8.

