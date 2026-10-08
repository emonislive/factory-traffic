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
