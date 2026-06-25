from __future__ import annotations

from dataclasses import replace
import re

from .models import EpisodeInput, PersonInput


_ROBOT_USER_LABEL_RE = re.compile(r"(?m)^(?P<indent>\s*)User\s*:")


def normalize_robot_speaker_labels(episode: EpisodeInput) -> EpisodeInput:
    """Replace generic robot speaker labels with the linked person label."""
    participant = _single_linked_speaker(episode.participants)
    if participant is None:
        return episode
    speaker_label = str(participant.display_name or participant.id).strip()
    if not speaker_label:
        return episode

    transcript = _replace_transcript_user_label(episode.transcript, speaker_label)
    if transcript == episode.transcript:
        return episode
    return replace(episode, transcript=transcript)


def _single_linked_speaker(participants: list[PersonInput]) -> PersonInput | None:
    """Return the only safe linked speaker for robot-labeled text."""
    speakers = [
        participant
        for participant in participants
        if participant.role.strip().casefold() == "speaker"
    ]
    if len(speakers) == 1:
        return speakers[0]
    if speakers:
        return None
    if len(participants) == 1:
        return participants[0]
    return None


def _replace_transcript_user_label(text: str, speaker_label: str) -> str:
    """Replace line-leading generic user speaker labels."""
    return _ROBOT_USER_LABEL_RE.sub(
        lambda match: f"{match.group('indent')}{speaker_label}:",
        text,
    )
