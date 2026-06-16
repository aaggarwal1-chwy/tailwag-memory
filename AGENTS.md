# Repository Agent Instructions

This repository uses documented agents as working scopes for Codex and human contributors.

Before making a non-trivial change:

1. Pick the active agent or agents from `.agents/README.md`.
2. Read each selected role card in `.agents/`.
3. Keep edits inside the selected agents' ownership boundaries.
4. Run the verification named by the selected role card when practical.
5. Record the work in `.agents/usage-log.md` with the date, task, active agents, and verification.

When using Codex platform subagents, prompt each spawned subagent to act as one named role from `.agents/`.
If a task spans multiple roles, keep write ownership separate and document the handoff.

The source of truth for trigger conditions remains `docs/agent-trigger-matrix.md`.
