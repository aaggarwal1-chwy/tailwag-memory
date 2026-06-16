from tailwag_memory.models import EpisodeInput
import unittest


class EpisodeInputTest(unittest.TestCase):
    def test_episode_input_from_dict_uses_caller_owned_ids(self) -> None:
        episode = EpisodeInput.from_dict(
            {
                "id": "episode_external_123",
                "episode_type": "conversation",
                "start_time": "2026-06-15T10:00:00+00:00",
                "end_time": None,
                "summary": "Jamie asked about chargers.",
                "transcript": "Jamie: Any chargers?",
                "retention_class": "standard",
                "visibility": "team",
                "place": {"building_code": "MAIN", "room_id": "101"},
                "participants": [
                    {
                        "id": "person_external_456",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "face_embedding": [0.1, 0.2],
                        "audio_embedding": [0.3, 0.4],
                    }
                ],
            }
        )

        self.assertEqual(episode.id, "episode_external_123")
        self.assertEqual(episode.participants[0].id, "person_external_456")
        self.assertEqual(episode.place.building_code, "MAIN")
        self.assertEqual(episode.place.room_id, "101")
        self.assertEqual(episode.participants[0].role, "participant")
        self.assertEqual(episode.participants[0].source, "caller")
        self.assertEqual(episode.participants[0].face_embedding, [0.1, 0.2])
        self.assertEqual(episode.participants[0].audio_embedding, [0.3, 0.4])


if __name__ == "__main__":
    unittest.main()
