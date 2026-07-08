from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..models import BiometricCandidate, BiometricSearchResult, OwnerResolutionResult


class TurnOwnerResolutionService:
    """Resolve the owner of one turn from face and voice evidence."""

    def resolve_turn_owner(
        self,
        *,
        primary_face_candidate: BiometricCandidate | dict[str, Any] | None = None,
        visible_face_candidates: list[BiometricCandidate | dict[str, Any]] | tuple[BiometricCandidate | dict[str, Any], ...] | None = None,
        voice_candidate: BiometricCandidate | dict[str, Any] | None = None,
        policy_context: dict[str, Any] | None = None,
    ) -> OwnerResolutionResult:
        policy = dict(policy_context or {})
        face = _candidate(primary_face_candidate)
        voice = _candidate(voice_candidate)
        visible_ids = {
            candidate.person_id
            for candidate in (_candidate(item) for item in (visible_face_candidates or ()))
            if candidate is not None and candidate.person_id
        }
        top_score = float(policy.get("voice_top_score", voice.score if voice else 0.0) or 0.0)
        runner_up_score = float(policy.get("voice_runner_up_score", 0.0) or 0.0)
        margin = float(policy.get("voice_margin", max(0.0, top_score - runner_up_score)) or 0.0)

        if voice is not None and voice.person_id:
            speaker_visible = voice.person_id in visible_ids or (not visible_ids and face is not None and voice.person_id == face.person_id)
            return OwnerResolutionResult(
                audio_speaker_id=voice.person_id,
                top_score=top_score,
                runner_up_score=runner_up_score,
                margin=margin,
                speaker_visible=speaker_visible,
                owner_id=voice.person_id,
                owner_source="audio_face_agree" if face is not None and voice.person_id == face.person_id else "audio",
                owner_confidence=top_score,
            )
        if face is not None and face.person_id:
            face_visible = face.person_id in visible_ids or not visible_ids
            return OwnerResolutionResult(
                audio_speaker_id=None,
                top_score=top_score,
                runner_up_score=runner_up_score,
                margin=margin,
                speaker_visible=face_visible,
                owner_id=face.person_id,
                owner_source="face",
                owner_confidence=0.0,
            )
        return OwnerResolutionResult(
            audio_speaker_id=None,
            top_score=top_score,
            runner_up_score=runner_up_score,
            margin=margin,
            speaker_visible=False,
            owner_id=None,
            owner_source="unknown",
            owner_confidence=0.0,
            unresolved_reason="no_confident_identity_evidence",
        )


def _candidate(value: BiometricCandidate | dict[str, Any] | None) -> BiometricCandidate | None:
    if value is None:
        return None
    if isinstance(value, BiometricCandidate):
        return value if value.person_id else None
    data = dict(value)
    person_id = str(data.get("person_id") or "").strip()
    if not person_id:
        return None
    return BiometricCandidate(
        person_id=person_id,
        display_name=str(data.get("display_name") or data.get("name") or ""),
        score=float(data.get("score") or data.get("similarity") or 0.0),
        consent_status=str(data.get("consent_status") or ""),
        reference_id=str(data.get("reference_id") or ""),
        model=str(data.get("model") or ""),
        metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {},
    )


def accepted_candidate(result: BiometricSearchResult | dict[str, Any] | None) -> BiometricCandidate | None:
    """Return the top candidate only when a biometric search accepted it."""
    if result is None:
        return None
    if isinstance(result, BiometricSearchResult):
        if result.recognized and result.candidates:
            return result.candidates[0]
        return None
    data = dict(result)
    if not bool(data.get("recognized")) and str(data.get("status") or "") != "accepted":
        return None
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    return _candidate(candidates[0])


def result_to_dict(result: OwnerResolutionResult) -> dict[str, Any]:
    return asdict(result)
