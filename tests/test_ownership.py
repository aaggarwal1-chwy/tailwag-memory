from tailwag_memory.models import BiometricCandidate
from tailwag_memory.ownership import TurnOwnerResolutionService
import unittest


class TurnOwnerResolutionServiceTest(unittest.TestCase):
    def test_voice_candidate_wins_and_marks_face_agreement(self) -> None:
        service = TurnOwnerResolutionService()

        result = service.resolve_turn_owner(
            primary_face_candidate=BiometricCandidate(person_id="person_jamie", score=0.9),
            visible_face_candidates=[BiometricCandidate(person_id="person_jamie", score=0.9)],
            voice_candidate=BiometricCandidate(person_id="person_jamie", score=0.8),
            policy_context={"voice_top_score": 0.8, "voice_runner_up_score": 0.2},
        )

        self.assertEqual(result.owner_id, "person_jamie")
        self.assertEqual(result.owner_source, "audio_face_agree")
        self.assertTrue(result.speaker_visible)

    def test_face_fallback_when_voice_is_missing(self) -> None:
        service = TurnOwnerResolutionService()

        result = service.resolve_turn_owner(
            primary_face_candidate={"person_id": "person_jamie", "score": 0.9},
            visible_face_candidates=[],
            voice_candidate=None,
        )

        self.assertEqual(result.owner_id, "person_jamie")
        self.assertEqual(result.owner_source, "face")


if __name__ == "__main__":
    unittest.main()
