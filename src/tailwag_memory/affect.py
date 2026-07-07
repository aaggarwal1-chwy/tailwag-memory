from __future__ import annotations

from dataclasses import asdict
import math
from pathlib import Path
from typing import Protocol

from .models import AffectScore, PersonEpisodeAffectPoint, PersonEpisodeTranscriptPoint


class AffectScoringProvider(Protocol):
    """Protocol for valence/arousal scoring providers."""

    def score(self, text: str) -> AffectScore:
        """Return a normalized valence/arousal score for text."""
        ...


class AffectScoringConfigurationError(RuntimeError):
    """Raised when affect scoring cannot be configured."""


class HuggingFaceXLMRobertaLargeAffectProvider:
    """Score text with one saved XLM-RoBERTa-large fold model."""

    def __init__(self, model_dir: str | Path, *, tokenizer_name: str = "xlm-roberta-large") -> None:
        """Load one external Hugging Face model directory."""
        self.model_dir = Path(model_dir)
        if not self.model_dir.exists() or not self.model_dir.is_dir():
            raise AffectScoringConfigurationError(f"affect model directory does not exist: {self.model_dir}")

        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise AffectScoringConfigurationError(
                "Install tailwag-memory[affect] to use Hugging Face affect scoring."
            ) from exc

        self._torch = torch
        self._model = AutoModelForSequenceClassification.from_pretrained(str(self.model_dir))
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
            self._tokenizer_source = str(self.model_dir)
        except OSError:
            self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
            self._tokenizer_source = tokenizer_name
        self._model.eval()

    def score(self, text: str) -> AffectScore:
        """Return normalized valence and arousal for text."""
        inputs = self._tokenizer(str(text), max_length=200, truncation=True, return_tensors="pt")
        with self._torch.no_grad():
            output = self._model(**inputs)
        values = output.logits.detach().cpu().flatten().tolist()
        if len(values) < 2:
            raise AffectScoringConfigurationError("affect model must return at least two labels: valence and arousal")
        valence = _finite_score(values[0], "valence")
        arousal = _finite_score(values[1], "arousal")
        return AffectScore(
            valence=valence,
            arousal=arousal,
            metadata={
                "model_dir": str(self.model_dir),
                "tokenizer": self._tokenizer_source,
                "architecture": "xlm-roberta-large",
            },
        )


class FoldEnsembleAffectProvider:
    """Average two affect scoring fold providers."""

    def __init__(self, fold1: AffectScoringProvider, fold2: AffectScoringProvider) -> None:
        """Store fold providers."""
        self.fold1 = fold1
        self.fold2 = fold2

    @classmethod
    def from_model_dirs(cls, fold1_model: str | Path, fold2_model: str | Path) -> "FoldEnsembleAffectProvider":
        """Build an ensemble from external Hugging Face fold directories."""
        return cls(
            HuggingFaceXLMRobertaLargeAffectProvider(fold1_model),
            HuggingFaceXLMRobertaLargeAffectProvider(fold2_model),
        )

    def score(self, text: str) -> AffectScore:
        """Return the mean score across fold1 and fold2."""
        fold1 = self.fold1.score(text)
        fold2 = self.fold2.score(text)
        valence = _finite_score((fold1.valence + fold2.valence) / 2, "valence")
        arousal = _finite_score((fold1.arousal + fold2.arousal) / 2, "arousal")
        return AffectScore(
            valence=valence,
            arousal=arousal,
            metadata={
                "scoring": "fold_mean",
                "architecture": "xlm-roberta-large",
                "folds": [asdict(fold1), asdict(fold2)],
            },
        )


def score_transcript_points(
    points: list[PersonEpisodeTranscriptPoint],
    provider: AffectScoringProvider,
) -> list[PersonEpisodeAffectPoint]:
    """Score transcript points with the supplied affect provider."""
    scored: list[PersonEpisodeAffectPoint] = []
    for point in points:
        score = provider.score(point.text)
        scored.append(
            PersonEpisodeAffectPoint(
                transcript=point,
                valence=score.valence,
                arousal=score.arousal,
                metadata=score.metadata,
            )
        )
    return scored


def _finite_score(value: float, label: str) -> float:
    """Return a finite float score or raise a configuration error."""
    rendered = float(value)
    if not math.isfinite(rendered):
        raise AffectScoringConfigurationError(f"{label} score must be finite")
    return rendered
