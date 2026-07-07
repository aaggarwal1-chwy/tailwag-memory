# Repository Agent Instructions

This repository uses project-scoped Codex custom agents as working scopes for Codex and human contributors.

Before making a non-trivial change:

1. Pick the active agent or agents from `.codex/agents/`.
2. Read each selected custom agent file.
3. Keep edits inside the selected agents' ownership boundaries.
4. Run the verification named by the selected custom agent when practical.

When using Codex platform subagents, spawn or prompt each subagent to act as one named custom agent from `.codex/agents/`.
If a task spans multiple roles, keep write ownership separate and document the handoff.

The source of truth for trigger conditions remains `docs/agent-trigger-matrix.md`.
