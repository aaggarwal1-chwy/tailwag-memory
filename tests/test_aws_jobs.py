from __future__ import annotations

import json
import unittest

from tailwag_memory.aws.jobs import (
    JobPayloadError,
    MemoryExtractEpisodeJob,
    RelayMaintenanceJob,
    ReportGenerateJob,
    SlackPollJob,
    job_to_json,
    parse_job_payload,
    parse_sqs_event,
)


class AwsJobPayloadTest(unittest.TestCase):
    def test_slack_poll_defaults_to_async_memory_extraction(self) -> None:
        job = parse_job_payload(
            {
                "job_type": "slack_poll",
                "job_id": "poll-1",
                "channel": "C123",
            }
        )

        self.assertIsInstance(job, SlackPollJob)
        self.assertEqual(job.channel, "C123")
        self.assertFalse(job.extract_memory)
        self.assertTrue(job.enqueue_memory_extraction)
        self.assertTrue(job.include_email)

    def test_memory_extract_job_parses_optional_person(self) -> None:
        job = parse_job_payload(
            json.dumps(
                {
                    "job_type": "memory_extract_episode",
                    "job_id": "extract-1",
                    "episode_id": "episode_1",
                    "person_id": "person_jamie",
                }
            )
        )

        self.assertEqual(job, MemoryExtractEpisodeJob(job_id="extract-1", episode_id="episode_1", person_id="person_jamie"))

    def test_report_job_parses_requested_reports(self) -> None:
        job = parse_job_payload(
            {
                "job_type": "report_generate",
                "job_id": "report-1",
                "reports": ["memory_items"],
                "output_prefix": "daily",
                "limit": 25,
            }
        )

        self.assertEqual(job, ReportGenerateJob(job_id="report-1", reports=["memory_items"], output_prefix="daily", limit=25))

    def test_relay_maintenance_job_parses_defaults(self) -> None:
        job = parse_job_payload(
            {
                "job_type": "relay_maintenance",
                "job_id": "relay-maintenance-1",
            }
        )

        self.assertEqual(job, RelayMaintenanceJob(job_id="relay-maintenance-1"))

    def test_relay_maintenance_job_parses_explicit_safety_window(self) -> None:
        job = parse_job_payload(
            {
                "job_type": "relay_maintenance",
                "job_id": "relay-maintenance-2",
                "now": "2026-07-23T12:00:00+00:00",
                "claim_timeout_seconds": 300,
            }
        )

        self.assertEqual(
            job,
            RelayMaintenanceJob(
                job_id="relay-maintenance-2",
                now="2026-07-23T12:00:00+00:00",
                claim_timeout_seconds=300,
            ),
        )

    def test_relay_maintenance_rejects_non_positive_claim_timeout(self) -> None:
        with self.assertRaisesRegex(JobPayloadError, "claim_timeout_seconds must be a positive integer"):
            parse_job_payload(
                {
                    "job_type": "relay_maintenance",
                    "job_id": "relay-maintenance-3",
                    "claim_timeout_seconds": 0,
                }
            )

    def test_job_to_json_is_stable(self) -> None:
        rendered = job_to_json(MemoryExtractEpisodeJob(job_id="extract-1", episode_id="episode_1"))

        self.assertEqual(
            rendered,
            '{"episode_id":"episode_1","job_id":"extract-1","job_type":"memory_extract_episode","person_id":null}',
        )

    def test_relay_maintenance_job_to_json_is_stable(self) -> None:
        rendered = job_to_json(
            RelayMaintenanceJob(
                job_id="relay-maintenance-1",
                now="2026-07-23T12:00:00+00:00",
                claim_timeout_seconds=180,
            )
        )

        self.assertEqual(
            rendered,
            '{"claim_timeout_seconds":180,"job_id":"relay-maintenance-1",'
            '"job_type":"relay_maintenance","now":"2026-07-23T12:00:00+00:00"}',
        )

    def test_rejects_invalid_job_type(self) -> None:
        with self.assertRaisesRegex(JobPayloadError, "unknown job_type"):
            parse_job_payload({"job_type": "unknown", "job_id": "job-1"})

    def test_rejects_non_positive_limits(self) -> None:
        with self.assertRaisesRegex(JobPayloadError, "history_limit must be a positive integer"):
            parse_job_payload(
                {
                    "job_type": "slack_poll",
                    "job_id": "poll-1",
                    "channel": "C123",
                    "history_limit": 0,
                }
            )

    def test_parse_sqs_event_returns_message_ids_and_jobs(self) -> None:
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"job_type":"memory_extract_episode","job_id":"extract-1","episode_id":"episode_1"}',
                }
            ]
        }

        parsed = parse_sqs_event(event)

        self.assertEqual(parsed[0][0], "msg-1")
        self.assertEqual(parsed[0][1], MemoryExtractEpisodeJob(job_id="extract-1", episode_id="episode_1"))


if __name__ == "__main__":
    unittest.main()
