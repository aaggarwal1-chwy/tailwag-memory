from __future__ import annotations

from typing import Any

from .jobs import WorkerJob, job_to_json


def send_job(sqs_client: Any, *, queue_url: str, job: WorkerJob) -> str | None:
    """Send one worker job to an SQS queue."""
    response = sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=job_to_json(job),
        MessageAttributes={
            "job_type": {"DataType": "String", "StringValue": job.job_type},
            "job_id": {"DataType": "String", "StringValue": job.job_id},
        },
    )
    message_id = response.get("MessageId")
    return str(message_id) if message_id is not None else None
