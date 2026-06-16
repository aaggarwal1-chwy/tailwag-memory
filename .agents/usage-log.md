# Agent Usage Log

Record each meaningful repo change here so agent usage is visible rather than implied.

| Date | Task | Active Agents | Verification |
| --- | --- | --- | --- |
| 2026-06-16 | Create concrete repo-local agent definitions and routing instructions. | Project Scaffold Agent, Documentation Agent | Added `AGENTS.md`, `.agents/README.md`, and per-agent role cards. Used a Codex platform explorer subagent to review the structure in parallel. Ran `PYTHONPATH=src python3 -m unittest discover -s tests` successfully. |
| 2026-06-16 | Add Slack channel polling that creates conversation memories from threads. | Ingestion Agent, CLI Mockup Agent, Test Agent, Documentation Agent | Ran `.venv/bin/python -m unittest discover -s tests` successfully. Verified `tailwag slack poll --help` through the repo venv. |
| 2026-06-16 | Add source adapter, integration contract, privacy/biometric review, scope guard, and release quality gate agents. Rename the command-surface role to CLI Mockup Agent. | Project Scaffold Agent, Documentation Agent | Updated `.agents/` role cards, `.agents/README.md`, and `docs/agent-trigger-matrix.md`. Ran `PYTHONPATH=src python3 -m unittest discover -s tests` successfully. |
| 2026-06-16 | Update Slack ingestion docs with continuous polling, private-channel scopes, inspection queries, and operator guide. | Documentation Agent, Integration Contract Agent | Checked docs against `tailwag slack poll --help`; no runtime behavior changes. |
