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

