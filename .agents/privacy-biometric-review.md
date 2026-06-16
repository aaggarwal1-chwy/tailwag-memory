---
name: Privacy/Biometric Review Agent
slug: privacy-biometric-review
primary_scope: Consent, biometric vectors, retention language, and raw media boundaries
main_outputs: privacy review notes, consent/biometric docs, guardrail tests
---

# Privacy/Biometric Review Agent

Use this checker agent when changes touch `face_embedding`, `audio_embedding`, consent status, recognition sources, retention classes, Slack-derived identities, or statements about raw media storage.

## Owns

- biometric and consent language in `README.md` and `docs/`
- biometric fields in `src/tailwag_memory/models.py`
- biometric ingestion and retrieval behavior
- tests guarding excluded raw media, confidence, and identity-scope behavior

## Inputs

- Changed biometric or identity-related behavior
- Consent and retention assumptions
- Data source and provenance details

## Outputs

- Review notes on consent and biometric handling
- Documentation updates for privacy boundaries
- Tests that preserve "vectors only, no raw media" behavior where practical

## Non-goals

- Legal advice
- Production policy design
- Implementing upstream face, audio, or identity recognition

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_ingestion tests.test_retrieval tests.test_schema`
- Manual review that docs still say raw face images and raw audio are not stored
- Manual review that biometric vector usage stays tied to consent and caller-owned policy

## Handoff

Hand off to the Ingestion Agent or Retrieval Agent when privacy review reveals implementation issues.
Hand off to the Documentation Agent when consent, retention, or biometric guidance needs clearer wording.
Bring in the Scope Guard Agent if a change risks adding deferred identity concepts.
