import json
from pathlib import Path
import unittest


class ExamplePayloadTest(unittest.TestCase):
    def test_example_payloads_cover_public_shapes_without_biometric_vectors(self) -> None:
        root = Path(__file__).resolve().parents[1]
        episode = json.loads((root / "examples/episode.json").read_text())
        existing_person_episode = json.loads((root / "examples/existing-person-episode.json").read_text())
        event = json.loads((root / "examples/event.json").read_text())
        person = episode["participants"][0]
        robot = episode["robots"][0]

        self.assertFalse((root / "examples/face-embedding.json").exists())
        self.assertFalse((root / "examples/audio-embedding.json").exists())
        self.assertEqual(person["id"], "person_jamie")
        self.assertEqual(person["display_name"], "Jamie")
        self.assertEqual(person["consent_status"], "consented")
        self.assertNotIn("face_embedding", person)
        self.assertNotIn("audio_embedding", person)
        self.assertEqual(robot, {
            "id": "cody",
            "display_name": "Cody",
            "role": "host",
            "source": "argos",
        })
        self.assertNotIn("robots", existing_person_episode)
        self.assertEqual(existing_person_episode["participants"][0], {
            "id": "person_jamie",
            "role": "speaker",
            "source": "example",
        })
        self.assertEqual(event["place"], {"building_code": "MAIN", "room_id": "101"})
        self.assertEqual(event["accepted_attendees"][0]["person"]["id"], "person_jamie")
        self.assertEqual(event["accepted_attendees"][0]["source"], "example")
        self.assertNotIn("participants", event)


if __name__ == "__main__":
    unittest.main()
