import json
from pathlib import Path
import unittest


class ExamplePayloadTest(unittest.TestCase):
    def test_biometric_example_vectors_match_default_dimension(self) -> None:
        root = Path(__file__).resolve().parents[1]
        face = json.loads((root / "examples/face-embedding.json").read_text())
        audio = json.loads((root / "examples/audio-embedding.json").read_text())
        episode = json.loads((root / "examples/episode.json").read_text())
        person = episode["participants"][0]

        self.assertEqual(len(face), 64)
        self.assertEqual(len(audio), 64)
        self.assertEqual(len(person["face_embedding"]), 64)
        self.assertEqual(len(person["audio_embedding"]), 64)


if __name__ == "__main__":
    unittest.main()
