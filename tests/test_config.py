import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tailwag_memory.config import (
    load_env_file,
    load_settings,
    parse_bounded_int_env,
    parse_positive_int_env,
    validate_relay_settings,
)


class ConfigTest(unittest.TestCase):
    def test_load_env_file_normalizes_quotes_and_preserves_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "runtime.env"
            env_path.write_text(
                "\n".join(
                    [
                        "# ignored comment",
                        "DOUBLE_QUOTED=\"double value\"",
                        "SINGLE_QUOTED='single value'",
                        "UNQUOTED= unquoted value ",
                        "EXISTING=file value",
                        "not-an-assignment",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EXISTING": "process value"}, clear=True):
                load_env_file(env_path)

                self.assertEqual(os.environ["DOUBLE_QUOTED"], "double value")
                self.assertEqual(os.environ["SINGLE_QUOTED"], "single value")
                self.assertEqual(os.environ["UNQUOTED"], "unquoted value")
                self.assertEqual(os.environ["EXISTING"], "process value")

    def test_parse_positive_int_env_uses_default_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(parse_positive_int_env("TAILWAG_EMBEDDING_DIMENSION", 64), 64)

    def test_parse_positive_int_env_rejects_non_positive_values(self) -> None:
        for value in ("0", "-1", "not-a-number"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TAILWAG_EMBEDDING_DIMENSION": value}, clear=True):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        parse_positive_int_env("TAILWAG_EMBEDDING_DIMENSION", 64)

    def test_parse_bounded_int_env_enforces_gateway_safe_range(self) -> None:
        with patch.dict(
            os.environ,
            {"TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS": "8"},
            clear=True,
        ):
            self.assertEqual(
                parse_bounded_int_env(
                    "TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS",
                    5,
                    minimum=1,
                    maximum=10,
                ),
                8,
            )
        for value in ("0", "11", "invalid"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {"TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS": value},
                    clear=True,
                ):
                    with self.assertRaisesRegex(ValueError, "between 1 and 10"):
                        parse_bounded_int_env(
                            "TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS",
                            5,
                            minimum=1,
                            maximum=10,
                        )

    def test_load_settings_parses_supported_runtime_env(self) -> None:
        env = {
            "NEO4J_URI": "bolt://example.test:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "password",
            "TAILWAG_EMBEDDING_DIMENSION": "128",
            "TAILWAG_EMBEDDING_MODEL": "text-embedding-3-large",
            "TAILWAG_FACE_EMBEDDING_MODEL": " facenet-vggface2 ",
            "TAILWAG_VOICE_EMBEDDING_MODEL": "ecapa",
            "TAILWAG_SYNTHESIS_MODEL": "gpt-5.5",
            "OPENAI_API_KEY": "test-key",
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "TAILWAG_AFFECT_FOLD1_MODEL": " /models/fold1 ",
            "TAILWAG_AFFECT_FOLD2_MODEL": "/models/fold2",
            "TAILWAG_RELAY_POLICY_MODEL": "gpt-5.5-mini",
            "TAILWAG_RELAY_DEFAULT_EXPIRY_DAYS": "14",
            "TAILWAG_RELAY_MAX_BODY_CHARACTERS": "400",
            "TAILWAG_RELAY_MAX_PENDING_PER_PAIR": "2",
            "TAILWAG_RELAY_MAX_SENDS_PER_SENDER_PER_DAY": "4",
            "TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS": "7",
            "TAILWAG_RELAY_POLICY_MAX_RETRIES": "0",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        self.assertEqual(settings.embedding_dimension, 128)
        self.assertEqual(settings.embedding_model, "text-embedding-3-large")
        self.assertEqual(settings.face_embedding_model, "facenet-vggface2")
        self.assertEqual(settings.voice_embedding_model, "ecapa")
        self.assertEqual(settings.synthesis_model, "gpt-5.5")
        self.assertEqual(settings.openai_api_key, "test-key")
        self.assertEqual(settings.slack_bot_token, "xoxb-test-token")
        self.assertEqual(settings.affect_fold1_model, "/models/fold1")
        self.assertEqual(settings.affect_fold2_model, "/models/fold2")
        self.assertEqual(settings.relay_policy_model, "gpt-5.5-mini")
        self.assertEqual(settings.relay_default_expiry_days, 14)
        self.assertEqual(settings.relay_max_body_characters, 400)
        self.assertEqual(settings.relay_max_pending_per_pair, 2)
        self.assertEqual(settings.relay_max_sends_per_sender_per_day, 4)
        self.assertEqual(settings.relay_policy_timeout_seconds, 7)
        self.assertEqual(settings.relay_policy_max_retries, 0)
        validate_relay_settings(settings)

    def test_relay_settings_preflight_requires_openai_key(self) -> None:
        from tests.helpers import test_settings

        settings = test_settings(openai_api_key=None)
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            validate_relay_settings(settings)

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
