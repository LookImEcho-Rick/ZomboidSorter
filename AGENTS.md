# Project guidance

This is a Windows-first Project Zomboid desktop mod manager. The current stack is Python 3.11+ and PySide6. Read `docs/ARCHITECTURE.md` before changing the structure.

## Workflow

- Read the relevant files in `docs/research/` before researching Project Zomboid or RimSort. Add only findings that reduce future work or clarify a decision.
- Prefer RimSort's source and official Project Zomboid material over summaries. Use focused reverse engineering only when a specific behavior remains unclear; do not install REA or another analysis dependency without user approval.
- Implement one milestone at a time. Finish and validate its acceptance criteria, document outcomes and limitations, then stop unless the active user request explicitly authorizes continuing through further milestones. The current project request authorizes sequential continuation.
- Keep the model small and explicit: a Workshop item can contain multiple `mod.info` entries, and an entry's Mod ID is not its Workshop ID. Do not import RimSort's game-specific formats or assume its sorting rules apply to Project Zomboid.
- Preserve Codex usage: inspect targeted files, reuse this research, avoid speculative features, and keep documentation concise.
- Validate important changes with focused fixtures and checks. State whether results are simulated or verified against an actual game installation; do not claim full integration from mocked tests alone.
- Keep discovery read-only. Before implementing configuration writes, verify the exact Build 42 target and format, back up existing data, use atomic replacement where possible, validate output, and never modify saves or delete installed mods without explicit approval.
- Report remaining limitations honestly and stop after the assigned milestone is complete.
