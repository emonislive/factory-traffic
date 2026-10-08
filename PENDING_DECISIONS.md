# PENDING_DECISIONS.md — Factory Traffic Management System

## Q-001 · Missing Problem Specification and Pre-requisite Phase 0 Artifacts
- Raised by / date: Agent A (Domain / Boost) / 2026-10-08
- Question: The task prompt was submitted with an unpopulated placeholder (`Problem: <paste the failing test and output>`), and the repository is at initial commit without Phase 0 scaffolding (`contracts/`, `backend/`, test harness, etc.). How should work proceed?
- Options (with trade-offs):
  1. Halt domain work until Phase 0 (Agent 0 from Instruction.md) is executed to create the repository skeleton, contracts, and test setup, and the specific failing test/output is provided. (Trade-off: requires user intervention to run Agent 0 first, but strictly preserves architecture, safety, and phase boundaries).
  2. Implement domain files (`backend/app/domain/`) out-of-order without contracts, dependencies, or test harness. (Trade-off: violates the Phase plan in Instruction.md section 4, bypasses Gate 1 human contract approval, and risks divergence from frozen contracts).
- Recommendation and why: Option 1. Phase 0 must run alone as mandated by Instruction.md section 4. Contracts must be frozen at Gate 1 before domain development begins. Additionally, without an actual failing test or error output, any domain bugfix is unspecified.
- Status: RESOLVED (2026-10-08 Gate 1 Review). Phase 0 scaffolding completed; contracts created in contracts/ and frozen; P-01..P-04 approved; initial domain test written and failing traceback captured for Agent A domain bugfix/boost.

---

## Gate 1 Review Record
- Date: 2026-10-08
- Contracts Reviewed:
  - `contracts/domain_types.py` & `backend/app/domain/types.py` (Enums: Direction, Phase, Signal, Mode, VehicleType, Step, CommandStatus; Configs: JunctionConfig, TimingsConfig; State: JunctionState, ManualState, EmergencyRecord, WaitingVehicle).
  - `contracts/schema.sql` (Tables: junctions, junction_state, vehicles, processed_events, direction_sequence, commands, device_status, audit_log; Indexes: partial unique on WAITING vehicles).
  - `contracts/openapi.yaml` (All 11 endpoints, uniform error response `{"error": {"code": ..., "message": ..., "details": ...}}`, live status schema).
  - `contracts/sse.md` (`event: status` on state commit, `: ping` heartbeat every 15s).
- Decisions Approved: P-01 (Orphan-clear ordering), P-02 (HTTP status mappings & endpoints), P-03 (Timer constants), P-04 (Degraded mode behavior).
- Contract Status: FROZEN. No modifications to `contracts/` without new PENDING_DECISIONS entry and human approval.

### Cross-agent requests
- None open at Gate 1. All Phase 0 scaffolding requested by Agent A is delivered.
