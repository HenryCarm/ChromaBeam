# BRIEFING — 2026-08-14T13:28:30Z

## Mission
Orchestrate the full implementation, refactoring, and automated validation of the ChromaBeam optical air-gapped file transfer suite.

## 🔒 My Identity
- Archetype: teamwork_preview_orchestrator
- Roles: orchestrator, user_liaison, human_reporter, successor
- Working directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/orchestrator_main
- Original parent: parent (caller)
- Original parent conversation ID: dfbecff5-316a-4a1d-b6c3-cd87dd68ef7c

## 🔒 My Workflow
- **Pattern**: Project Pattern
- **Scope document**: /home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md
1. **Decompose**: Survey full scope via 3 Explorers, create PROJECT.md (architecture, feature inventory, milestones, interface contracts), decompose into implementation track milestones + E2E testing track.
2. **Dispatch & Execute**:
   - Top-level: Dispatch sub-orchestrators for milestones or run iteration loop directly.
   - Dual-track: Spawn E2E Testing Orchestrator alongside Implementation track.
3. **On failure**: Retry -> Replace -> Skip (non-auditor) -> Redistribute -> Redesign.
4. **Succession**: Self-succeed when cumulative subagent spawn count reaches 16.
- **Work items**:
  1. Survey phase (3 parallel Explorers) [in-progress]
  2. Architecture & Decomposition (PROJECT.md & TEST_INFRA.md) [pending]
  3. Milestone Execution & E2E Test Suite [pending]
  4. Full Loopback Verification & Forensic Audit [pending]
- **Current phase**: 0 (Survey)
- **Current focus**: Survey codebase and requirements with 3 Explorers

## 🔒 Key Constraints
- NEVER write, modify, or create source code files directly.
- NEVER run build/test commands yourself — require workers/subagents to do so.
- NEVER investigate or explore code directly — dispatch Explorers.
- Only write metadata/state files (.md) in .agents/ folder.
- Python environment: Strictly use `/home/henry/Documents/Projects/Python/venv/bin/python`. Never create local `.venv`.
- Safe file deletion: Move files to `/home/henry/Documents/Projects/OpenCode/tmp/Trash`.
- Auditor verdict is a BINARY VETO.
- Never reuse subagents after handoff.

## Current Parent
- Conversation ID: dfbecff5-316a-4a1d-b6c3-cd87dd68ef7c
- Updated: 2026-08-14T13:28:30Z

## Key Decisions Made
- Starting with Phase 0 Survey: Spawning 3 parallel explorers to inspect existing codebase structure, dependencies, web/python architecture, and test harnesses.

## Team Roster
| Agent | Type | Work Item | Status | Conv ID |
|-------|------|-----------|--------|---------|
| explorer_survey_1 | teamwork_preview_explorer | Codebase Architecture Survey | failed/replaced | ca1773f8-edc5-497c-9291-d38864525d43 |
| explorer_survey_2 | teamwork_preview_explorer | CV, Finder Pattern & Homography Survey | completed | 8084a458-b207-4442-9a9d-e941e5d8dd15 |
| explorer_survey_3 | teamwork_preview_explorer | Multi-Mode, Worker & E2E Testing Survey | failed/replaced | fef7ad97-02a9-46d2-bf56-7e6ce90fdc9b |
| explorer_survey_1_rep | teamwork_preview_explorer | Codebase Architecture Survey (Rep) | completed | 07c425c7-67a8-4988-8e8c-59c7aaf98fb5 |
| explorer_survey_3_rep | teamwork_preview_explorer | Multi-Mode, Worker & E2E Testing Survey (Rep) | completed | cbc49fa4-ff1f-47d6-86cb-a708bc339a38 |
| worker_m1 | teamwork_preview_worker | Anchor Standard & Core Color Matrix (M1) | completed | 559ac724-c9a0-4995-b6a7-2676d7d55a2b |
| worker_m2 | teamwork_preview_worker | Python CV Tracker & 4-Way Homography (M2) | failed/hung | f9c347d7-459f-4736-ae43-d516788dd407 |
| worker_m3 | teamwork_preview_worker | Web Worker Inlining & Bundler (M3) | completed | d43067ad-7a6b-472a-aeb7-49c9b27538da |
| worker_m2_rep | teamwork_preview_worker | Python CV Tracker & 4-Way Homography (M2 Rep) | completed | df48229f-922a-4e92-89b0-50010e892ac9 |
| test_writer_m4 | teamwork_preview_test_writer | Optical Loopback & E2E Test Suite (M4) | completed | d325f400-ba9b-475a-9894-ae8fb7fc3284 |
| worker_m1_harden | teamwork_preview_worker | Color Matrix Distance Hardening | in-progress | 8facc225-f017-4cf0-8619-b589790f7722 |

## Succession Status
- Succession required: no
- Spawn count: 11 / 16
- Pending subagents: 8facc225-f017-4cf0-8619-b589790f7722
- Predecessor: none
- Successor: not yet spawned

## Active Timers
- Heartbeat cron: task-11 (*/10 * * * *)
- Safety timer: none

## Artifact Index
- `/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/ORIGINAL_REQUEST.md` — User request specifications
- `/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/orchestrator_main/BRIEFING.md` — Persistent working memory
- `/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/orchestrator_main/progress.md` — State checkpoint and liveness
