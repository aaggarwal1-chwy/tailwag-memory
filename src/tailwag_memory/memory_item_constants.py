from __future__ import annotations

MEMORY_ITEM_KINDS = {"preference", "boundary", "pet", "fact", "followup"}
MEMORY_ITEM_SOURCES = {"caller", "calling-system", "live_chat", "slack", "argos"}
MEMORY_ITEM_STATUSES = {"active", "addressed", "superseded"}
PINNED_MEMORY_KEYS = {"preferred_name", "preferred_language", "nickname_for_robot", "birthday"}
DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES = 4
DEFAULT_CONSOLIDATION_SEED_LIMIT = 25
DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT = 12
DEFAULT_CONSOLIDATION_CLUSTER_LIMIT = 8
DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT = 1200
IDENTITY_OWNED_PREFIXES = (
    "team:",
    "title:",
    "business title:",
    "tenure:",
    "manager:",
    "manager name:",
    "cost center:",
    "business function:",
    "leadership org:",
    "senior leadership team:",
    "job family:",
    "job level:",
    "c level:",
)
TRANSIENT_TASK_MARKERS = (
    "today",
    "tomorrow",
    "this morning",
    "this afternoon",
    "this evening",
    "tonight",
    "this week",
    "right now",
    "currently",
    "at the moment",
)
TRANSIENT_TASK_TOPICS = (
    "bug",
    "debug",
    "debugging",
    "broken",
    "failing",
    "failure",
    "incident",
    "outage",
    "blocked",
    "stuck",
    "deadline",
    "todo",
    "to do",
    "task",
)
MEMORY_EXTRACTION_DEVELOPER_PROMPT = """
Task:
Extract durable person memory from a transcript for a workplace social agent.
Extract only for the target person. In multi-speaker transcripts, only create memory that is explicitly stated by the
target person or explicitly about the target person.

Durability rules:
Create a durable memory only when it is likely to stay relevant for weeks at a time and make future conversation more fruitful:
stable preferences, boundaries, enduring personal context, or facts the agent can use again without sounding stale.
Insignificant observations, one-off comments, brief task statuses, and details only useful in the current conversation
are not durable memory. If the transcript does not contain that level of signal, return update false and no ops.

Allowed kinds:
preference, boundary, pet, fact, and followup.

Allowed operations:
create, address, support, and noop. Return JSON only with update and ops.

Create rules:
Create new memories only for new durable information. Facts must be narrow person-prompt context, not ontology
triples, inferred traits, directory attributes, current task status, short-lived problems, or general world knowledge.
Near-term conversational hooks, open tasks, transient blockers, bugs being debugged today, meetings, travel,
appointments, or anything that would be awkward to mention weeks later must be followup, not fact or preference.
Do not create a duplicate followup when an existing followup in existing_memories already covers the topic. Use
support when the transcript is relevant evidence for an existing followup but does not answer, complete, cancel, or
supersede it.

Address rules:
Use address when the new transcript explicitly answers, completes, cancels, or supersedes an existing followup. Only
address followups present in existing_memories; Tailwag gathers active, unaddressed, currently relevant followups as
the current context for this person. Do not address facts, preferences, boundaries, pets, unknown memory IDs, or
followups that are not in existing_memories.

Support rules:
Use support when the new transcript is clearly related to an existing followup and should be retained as evidence,
but the followup is still open. Only support followups present in existing_memories. Do not support facts,
preferences, boundaries, pets, unknown memory IDs, or followups that are not in existing_memories.

Followup timing rules:
Followups must include expires_at and should include due_at only when the transcript states or strongly implies when
the followup becomes useful. Use the current_time value as the evidence time for relative phrases. If the timing is
vague, do not create a followup; recent episode context can carry short-lived conversational hooks. For clear event,
meeting, travel, deadline, blocker, or task windows, set due_at to the first useful opportunity after that window and
expire soon after the useful conversation window. Same-day bugs or tasks should normally expire within a week.

Do not store:
Do not create notes. Do not store org chart, title, manager, team, cost center, or inferred personality.
""".strip()
MEMORY_EXTRACTION_TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "memory_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "update": {"type": "boolean"},
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "op": {"type": "string", "enum": ["create", "address", "support", "noop"]},
                            "memory_id": {"type": "string"},
                            "kind": {"type": "string", "enum": ["preference", "boundary", "pet", "fact", "followup"]},
                            "key": {"type": "string"},
                            "summary": {"type": "string"},
                            "observed_at": {"type": "string"},
                            "due_at": {"type": "string"},
                            "expires_at": {"type": "string"},
                            "metadata": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {},
                                "required": [],
                            },
                        },
                        "required": [
                            "op",
                            "memory_id",
                            "kind",
                            "key",
                            "summary",
                            "observed_at",
                            "due_at",
                            "expires_at",
                            "metadata",
                        ],
                    },
                },
            },
            "required": ["update", "ops"],
        },
    }
}
MEMORY_CONSOLIDATION_DEVELOPER_PROMPT = (
    "Consolidate repeated person memory patterns from supplied episode clusters for a workplace social agent. "
    "Extract only durable person memory for the target person. Every create or merge operation must be "
    "supported by distinct episode IDs from the supplied clusters. Do not invent episode IDs. Create memory "
    "only when at least the required minimum number of supplied episodes directly support the same narrow claim. "
    "Merge related memories when one active merged memory can preserve all non-duplicative durable details in one place; "
    "do not silently discard conflicting details. "
    "Allowed kinds are preference, boundary, pet, fact, and followup. Facts must be narrow person-prompt context, "
    "not ontology triples, inferred traits, directory attributes, current task status, short-lived problems, "
    "or general world knowledge. Near-term hooks, open tasks, transient blockers, meetings, appointments, and "
    "same-day bugs must be followup, not fact or preference, and followups require expires_at. Create followups only "
    "when the evidence states or strongly implies a useful timing window; skip vague followups rather than guessing. "
    "Do not store org chart, "
    "title, manager, team, cost center, or inferred personality. Merge existing memories instead of updating them. "
    "For merge ops, memory_ids contains source memory IDs to supersede. Return JSON only with update and ops."
)
MEMORY_CONSOLIDATION_TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "memory_consolidation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "update": {"type": "boolean"},
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "op": {"type": "string", "enum": ["create", "merge", "noop"]},
                            "memory_id": {"type": "string"},
                            "memory_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "kind": {"type": "string", "enum": ["preference", "boundary", "pet", "fact", "followup"]},
                            "key": {"type": "string"},
                            "summary": {"type": "string"},
                            "observed_at": {"type": "string"},
                            "due_at": {"type": "string"},
                            "expires_at": {"type": "string"},
                            "supported_episode_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "metadata": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {},
                                "required": [],
                            },
                        },
                        "required": [
                            "op",
                            "memory_id",
                            "memory_ids",
                            "kind",
                            "key",
                            "summary",
                            "observed_at",
                            "due_at",
                            "expires_at",
                            "supported_episode_ids",
                            "metadata",
                        ],
                    },
                },
            },
            "required": ["update", "ops"],
        },
    }
}
