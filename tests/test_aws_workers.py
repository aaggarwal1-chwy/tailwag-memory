from __future__ import annotations

import unittest

from tailwag_memory.aws.handlers import _handle_sqs_jobs
from tailwag_memory.aws.idempotency import DynamoDBJobIdempotencyStore, InMemoryJobIdempotencyStore
from tailwag_memory.aws.jobs import MemoryExtractEpisodeJob
from tailwag_memory.aws.reports import publish_report_files
from tailwag_memory.aws.sqs import send_job


class ConditionalCheckFailedException(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeDynamoTable:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}
        self.updates: list[dict[str, object]] = []

    def put_item(self, *, Item, ConditionExpression):
        if Item["job_id"] in self.items:
            raise ConditionalCheckFailedException()
        self.items[Item["job_id"]] = dict(Item)

    def get_item(self, *, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item is not None else {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        key = kwargs["Key"]["job_id"]
        item = self.items.get(key)
        values = kwargs["ExpressionAttributeValues"]
        condition = kwargs.get("ConditionExpression", "")
        if condition.startswith("attribute_not_exists"):
            reclaimable = item is None or item.get("status") == "failed" or (
                item.get("status") == "running"
                and item.get("lease_expires_at", 0) <= values[":now"]
            )
            if not reclaimable:
                raise ConditionalCheckFailedException()
        elif condition:
            if item is None or item.get("status") != values[":running"] or item.get("claim_token") != values[":claim_token"]:
                raise ConditionalCheckFailedException()
        if item is None:
            item = {"job_id": key}
            self.items[key] = item
        if ":job_type" in values:
            item["job_type"] = values[":job_type"]
        if ":running" in values and "attempt_count" in kwargs["UpdateExpression"]:
            item["status"] = values[":running"]
            item["lease_expires_at"] = values[":lease_expires_at"]
            item["claim_token"] = values[":claim_token"]
            item["expires_at"] = values[":expires_at"]
            item["attempt_count"] = int(item.get("attempt_count", 0)) + values[":attempt_increment"]
            item.pop("error", None)
            item.pop("result", None)
        if ":status" in values:
            item["status"] = values[":status"]
        if ":updated_at" in values:
            item["updated_at"] = values[":updated_at"]
        if ":result" in values:
            item["result"] = values[":result"]
        if ":error" in values:
            item["error"] = values[":error"]
        return {"Attributes": dict(item)}


class FakeSqsClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": f"msg-{len(self.messages)}"}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: list[dict[str, object]] = []

    def put_object(self, **kwargs):
        self.objects.append(kwargs)


class AwsWorkerHelpersTest(unittest.TestCase):
    def test_dynamodb_idempotency_claims_job_once(self) -> None:
        table = FakeDynamoTable()
        store = DynamoDBJobIdempotencyStore(table)

        first = store.start_job("job-1", job_type="memory_extract_episode")
        second = store.start_job("job-1", job_type="memory_extract_episode")

        self.assertTrue(first.started)
        self.assertFalse(second.started)
        self.assertEqual(second.status, "running")

    def test_dynamodb_idempotency_reclaims_failure_and_marks_success(self) -> None:
        table = FakeDynamoTable()
        store = DynamoDBJobIdempotencyStore(table)
        first = store.start_job("job-1", job_type="memory_extract_episode")

        self.assertTrue(first.started)
        self.assertIsNotNone(first.claim_token)
        store.mark_failed("job-1", claim_token=first.claim_token or "", error="boom")
        retry = store.start_job("job-1", job_type="memory_extract_episode")
        store.mark_succeeded("job-1", claim_token=retry.claim_token or "", result={"ok": True})

        self.assertTrue(retry.started)
        self.assertEqual(table.items["job-1"]["status"], "succeeded")
        self.assertEqual(table.items["job-1"]["attempt_count"], 2)
        self.assertEqual(table.items["job-1"]["result"], {"ok": True})
        reclaim_update = table.updates[2]
        self.assertIn("attempt_count :attempt_increment", reclaim_update["UpdateExpression"])
        self.assertIn("lease_expires_at <= :now", reclaim_update["ConditionExpression"])

    def test_sqs_send_job_serializes_payload_and_attributes(self) -> None:
        sqs = FakeSqsClient()
        message_id = send_job(
            sqs,
            queue_url="https://sqs.example/queue",
            job=MemoryExtractEpisodeJob(job_id="extract-1", episode_id="episode_1"),
        )

        self.assertEqual(message_id, "msg-1")
        self.assertEqual(sqs.messages[0]["QueueUrl"], "https://sqs.example/queue")
        self.assertIn('"episode_id":"episode_1"', sqs.messages[0]["MessageBody"])
        self.assertEqual(
            sqs.messages[0]["MessageAttributes"]["job_type"]["StringValue"],
            "memory_extract_episode",
        )

    def test_handler_dispatch_marks_success(self) -> None:
        store = InMemoryJobIdempotencyStore()
        calls: list[str] = []
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"job_type":"memory_extract_episode","job_id":"extract-1","episode_id":"episode_1"}',
                }
            ]
        }

        response = _handle_sqs_jobs(
            event,
            lambda job: calls.append(job.job_id) or {"ok": True},
            idempotency_store=store,
        )

        self.assertEqual(response, {"batchItemFailures": []})
        self.assertEqual(calls, ["extract-1"])
        self.assertEqual(store.items["extract-1"]["status"], "succeeded")

    def test_handler_dispatch_returns_partial_batch_failure(self) -> None:
        store = InMemoryJobIdempotencyStore()
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"job_type":"memory_extract_episode","job_id":"extract-1","episode_id":"episode_1"}',
                }
            ]
        }

        def fail(job):
            raise RuntimeError("model unavailable")

        response = _handle_sqs_jobs(event, fail, idempotency_store=store)

        self.assertEqual(response, {"batchItemFailures": [{"itemIdentifier": "msg-1"}]})
        self.assertEqual(store.items["extract-1"]["status"], "failed")

    def test_handler_retries_the_same_failed_message_until_it_succeeds(self) -> None:
        store = InMemoryJobIdempotencyStore()
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": "{\"job_type\":\"memory_extract_episode\",\"job_id\":\"extract-1\",\"episode_id\":\"episode_1\"}",
                }
            ]
        }
        calls: list[str] = []

        def fail(job):
            calls.append(job.job_id)
            raise RuntimeError("model unavailable")

        for _ in range(3):
            self.assertEqual(
                _handle_sqs_jobs(event, fail, idempotency_store=store),
                {"batchItemFailures": [{"itemIdentifier": "msg-1"}]},
            )

        self.assertEqual(calls, ["extract-1", "extract-1", "extract-1"])
        self.assertEqual(store.items["extract-1"]["attempt_count"], 3)
        self.assertEqual(store.items["extract-1"]["status"], "failed")

    def test_running_job_is_reclaimed_after_its_lease_expires(self) -> None:
        now = [100]
        store = InMemoryJobIdempotencyStore(lease_seconds=10, clock=lambda: now[0])
        first = store.start_job("job-1", job_type="memory_extract_episode")
        now[0] = 109
        self.assertFalse(store.start_job("job-1", job_type="memory_extract_episode").started)
        now[0] = 110
        retry = store.start_job("job-1", job_type="memory_extract_episode")

        self.assertTrue(retry.started)
        self.assertEqual(store.items["job-1"]["attempt_count"], 2)
        self.assertNotEqual(first.claim_token, retry.claim_token)

    def test_publish_report_files_writes_prefixed_s3_objects(self) -> None:
        s3 = FakeS3Client()

        published = publish_report_files(
            s3,
            bucket="tailwag-reports",
            output_prefix="daily/2026-07-14",
            files={"tailwag-memory-items.html": ("<html></html>", "text/html; charset=utf-8")},
        )

        self.assertEqual(published[0].key, "daily/2026-07-14/tailwag-memory-items.html")
        self.assertEqual(s3.objects[0]["Bucket"], "tailwag-reports")
        self.assertEqual(s3.objects[0]["Body"], b"<html></html>")


if __name__ == "__main__":
    unittest.main()
