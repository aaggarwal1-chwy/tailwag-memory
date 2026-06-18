---
name: Project Scaffold Agent
slug: project-scaffold
primary_scope: Repo structure and local developer workflow
main_outputs: package files, Docker Compose, .env.example, folders
---

# Project Scaffold Agent

Use this agent when the repository shape, package metadata, local setup, or folder layout needs to change.

## Owns

- `pyproject.toml`
- `docker-compose.yml`
- `.env.example`
- top-level package, test, docs, scripts, and example directories
- local developer workflow assumptions

## Inputs

- Desired stack
- Current repo state
- Local development assumptions

## Outputs

- Package files
- Docker Compose configuration
- Environment examples
- Package directories
- Test directories

## Non-goals

- Cypher implementation
- Ingestion behavior
- Retrieval behavior

## Verification

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- Manual review of local setup instructions when package or environment files change

## Handoff

Hand off to the Neo4j Schema Agent when scaffold changes expose schema setup work.
Hand off to the CLI Mockup Agent when scaffold changes require developer commands.
Hand off to the Documentation Agent when setup instructions change.
