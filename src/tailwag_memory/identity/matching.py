"""Name normalization and candidate-ranking policy for directory identity."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

try:  # pragma: no cover - exercised when optional dependency is available.
    from rapidfuzz import fuzz as rapidfuzz_fuzz
    from rapidfuzz.distance import JaroWinkler as rapidfuzz_jaro_winkler
except Exception:  # pragma: no cover - fallback keeps tests/dev envs lightweight.
    rapidfuzz_fuzz = None
    rapidfuzz_jaro_winkler = None

from ..models import DirectoryPersonRecord, IdentityCandidate


MAX_CANDIDATES = 3
MIN_PLAUSIBLE_SCORE = 74.0
CLARIFY_SCORE = 84.0
AUTO_CONFIRM_SCORE = 98.0
CLEAR_GAP_SCORE = 5.0
MULTIPLE_MATCH_GAP = 3.0


def rank_candidates(
    query_name: str,
    records: list[DirectoryPersonRecord],
    *,
    min_plausible_score: float = MIN_PLAUSIBLE_SCORE,
    max_candidates: int = MAX_CANDIDATES,
) -> list[IdentityCandidate]:
    ranked: list[IdentityCandidate] = []
    normalized_query = normalize_name(query_name)
    token_query = token_sort_key(query_name)
    for record in records:
        name_score = score_ratio(normalized_query, normalize_name(record.official_name))
        token_score = score_ratio(token_query, token_sort_key(record.official_name))
        score = max(name_score, token_score)
        if score < min_plausible_score:
            continue
        ranked.append(
            IdentityCandidate(
                official_name=record.official_name,
                username=record.username,
                employee_email=record.employee_email,
                business_title=record.business_title,
                tenure=record.tenure,
                manager_name=record.manager_name,
                score=score,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.official_name.casefold(), item.username))
    return ranked[:max_candidates]


def build_query_identity(
    *, shared_first_name: str, shared_last_name: str, shared_name: str
) -> tuple[str, str, str]:
    first_name = normalize_name(shared_first_name)
    last_name = normalize_name(shared_last_name)
    full_name = normalize_name(shared_name)
    if not first_name and not last_name and full_name:
        parts = full_name.split()
        first_name = parts[0] if parts else ""
        last_name = parts[-1] if len(parts) > 1 else ""
    elif full_name and (not first_name or not last_name):
        parts = full_name.split()
        first_name = first_name or (parts[0] if parts else "")
        last_name = last_name or (parts[-1] if len(parts) > 1 else "")
    if not full_name:
        full_name = " ".join(part for part in (first_name, last_name) if part)
    return full_name, first_name, last_name


def normalize_name(value: str) -> str:
    normalized = "".join(
        character.lower() if character.isalnum() else " " for character in str(value or "")
    )
    return " ".join(normalized.split())


def token_sort_key(value: str) -> str:
    normalized = normalize_name(value)
    return " ".join(sorted(normalized.split())) if normalized else ""


def score_ratio(
    left: str,
    right: str,
    *,
    fuzz: Any = rapidfuzz_fuzz,
    jaro_winkler: Any = rapidfuzz_jaro_winkler,
) -> float:
    if not left or not right:
        return 0.0
    if fuzz is not None and jaro_winkler is not None:
        return float(
            max(
                fuzz.WRatio(left, right),
                fuzz.ratio(left, right),
                100.0 * jaro_winkler.normalized_similarity(left, right),
            )
        )
    return 100.0 * SequenceMatcher(a=left, b=right).ratio()
