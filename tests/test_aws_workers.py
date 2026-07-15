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
        item = self.items.setdefault(key, {"job_id": key})
        values = kwargs["ExpressionAttributeValues"]
        if ":status" in values:
            item["status"] = values[":status"]
        if ":result" in values:
            item["result"] = values[":result"]
        if ":error" in values:
            item["error"] = values[":error"]


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

    def test_dynamodb_idempotency_marks_success_and_failure(self) -> None:
        table = FakeDynamoTable()
        store = DynamoDBJobIdempotencyStore(table)
        store.start_job("job-1", job_type="memory_extract_episode")

        store.mark_succeeded("job-1", result={"ok": True})
        store.mark_failed("job-1", error="boom")

        self.assertEqual(table.items["job-1"]["status"], "failed")
        self.assertEqual(table.items["job-1"]["result"], {"ok": True})
        self.assertEqual(table.items["job-1"]["error"], "boom")
        success_update = table.updates[0]
        self.assertIn("#result = :result", success_update["UpdateExpression"])
        self.assertEqual(success_update["ExpressionAttributeNames"]["#result"], "result")
        failure_update = table.updates[1]
        self.assertIn("#error = :error", failure_update["UpdateExpression"])
        self.assertEqual(failure_update["ExpressionAttributeNames"]["#error"], "error")

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
