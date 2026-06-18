import json
from pathlib import Path
import unittest


class ExamplePayloadTest(unittest.TestCase):
    def test_biometric_example_vectors_match_default_dimension(self) -> None:
        root = Path(__file__).resolve().parents[1]
        face = json.loads((root / "examples/face-embedding.json").read_text())
        audio = json.loads((root / "examples/audio-embedding.json").read_text())
        episode = json.loads((root / "examples/episode.json").read_text())
        existing_person_episode = json.loads((root / "examples/existing-person-episode.json").read_text())
        event = json.loads((root / "examples/event.json").read_text())
        person = episode["participants"][0]

        self.assertEqual(len(face), 64)
        self.assertEqual(len(audio), 64)
        self.assertEqual(len(person["face_embedding"]), 64)
        self.assertEqual(len(person["audio_embedding"]), 64)
        self.assertEqual(person["face_embedding"], face)
        self.assertEqual(person["audio_embedding"], audio)
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
