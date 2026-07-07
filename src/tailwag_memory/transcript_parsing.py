from __future__ import annotations

from dataclasses import dataclass
import re

_SPEAKER_TURN_RE_TEMPLATE = r"(?:^|\s)(?:\[(?P<timestamp>[^\]]+)\]\s*)?(?P<speaker>{choices}):\s*"


@dataclass(frozen=True)
class TranscriptTurn:
    """One parsed transcript turn."""

    timestamp: str
    speaker: str
    text: str


def target_transcript_turns(
    transcript: str,
    *,
    person_id: str,
    display_name: str,
    speaker_labels: list[str],
) -> list[TranscriptTurn]:
    """Return transcript turns spoken by the target person."""
    labels = {
        normalize_speaker_label(label)
        for label in [display_name, person_id]
        if normalize_speaker_label(label)
    }
    if not labels:
        return []

    matcher = speaker_turn_pattern([*speaker_labels, display_name, person_id, "Assistant", "User"])
    if matcher is None:
        return []

    turns: list[TranscriptTurn] = []
    for raw_line in transcript.splitlines():
        matches = list(matcher.finditer(raw_line))
        for index, match in enumerate(matches):
            speaker = match.group("speaker").strip()
            if normalize_speaker_label(speaker) not in labels:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_line)
            text = raw_line[match.end() : end].strip()
            if not text:
                continue
            turns.append(
                TranscriptTurn(
                    timestamp=(match.group("timestamp") or "").strip(),
                    speaker=speaker,
                    text=text,
                )
            )
    return turns


def normalize_speaker_label(value: str) -> str:
    """Normalize a transcript speaker label for exact matching."""
    return " ".join(str(value or "").strip().casefold().split())


def speaker_turn_pattern(labels: list[str]) -> re.Pattern[str] | None:
    """Build a speaker-turn matcher from known labels."""
    normalized: dict[str, str] = {}
    for label in labels:
        rendered = str(label or "").strip()
        if not rendered:
            continue
        normalized.setdefault(normalize_speaker_label(rendered), rendered)
    if not normalized:
        return None
    choices = "|".join(re.escape(label) for label in sorted(normalized.values(), key=len, reverse=True))
    return re.compile(_SPEAKER_TURN_RE_TEMPLATE.format(choices=choices))
