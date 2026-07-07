import os
import unittest
from unittest.mock import patch

from tailwag_memory.config import load_settings, parse_positive_int_env


class ConfigTest(unittest.TestCase):
    def test_parse_positive_int_env_uses_default_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(parse_positive_int_env("TAILWAG_EMBEDDING_DIMENSION", 64), 64)

    def test_parse_positive_int_env_rejects_non_positive_values(self) -> None:
        for value in ("0", "-1", "not-a-number"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TAILWAG_EMBEDDING_DIMENSION": value}, clear=True):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        parse_positive_int_env("TAILWAG_EMBEDDING_DIMENSION", 64)

    def test_load_settings_parses_supported_runtime_env(self) -> None:
        env = {
            "NEO4J_URI": "bolt://example.test:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "password",
            "TAILWAG_EMBEDDING_DIMENSION": "128",
            "TAILWAG_EMBEDDING_MODEL": "text-embedding-3-large",
            "TAILWAG_SYNTHESIS_MODEL": "gpt-5.5",
            "OPENAI_API_KEY": "test-key",
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "TAILWAG_AFFECT_FOLD1_MODEL": " /models/fold1 ",
            "TAILWAG_AFFECT_FOLD2_MODEL": "/models/fold2",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        self.assertEqual(settings.embedding_dimension, 128)
        self.assertEqual(settings.embedding_model, "text-embedding-3-large")
        self.assertEqual(settings.synthesis_model, "gpt-5.5")
        self.assertEqual(settings.openai_api_key, "test-key")
        self.assertEqual(settings.slack_bot_token, "xoxb-test-token")
        self.assertEqual(settings.affect_fold1_model, "/models/fold1")
        self.assertEqual(settings.affect_fold2_model, "/models/fold2")

    def test_load_settings_treats_blank_affect_model_env_as_missing(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TAILWAG_AFFECT_FOLD1_MODEL": " ",
                "TAILWAG_AFFECT_FOLD2_MODEL": "",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertIsNone(settings.affect_fold1_model)
        self.assertIsNone(settings.affect_fold2_model)


if __name__ == "__main__":
    unittest.main()
