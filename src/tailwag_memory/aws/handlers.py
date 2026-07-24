from __future__ import annotations

from dataclasses import asdict, is_dataclass
import os
from typing import Any, Callable

from tailwag_memory.client import TailwagMemoryClient
from tailwag_memory.config import load_settings
from tailwag_memory.slack_ingestion import SlackMemoryPoller, SlackWebApiClient

from .idempotency import DynamoDBJobIdempotencyStore, IdempotencyClaimLost
from .jobs import (
    MemoryConsolidateAllJob,
    MemoryConsolidatePersonJob,
    MemoryExtractEpisodeJob,
    RelayMaintenanceJob,
    ReportGenerateJob,
    SlackPollJob,
    WorkerJob,
    parse_sqs_event,
)
from .reports import publish_report_files, render_report_files


def slack_poll_handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    """Lambda handler for Slack polling SQS events."""
    return _handle_sqs_jobs(event, _process_slack_poll_job)


def memory_worker_handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    """Lambda handler for memory extraction and consolidation SQS events."""
    return _handle_sqs_jobs(event, _process_memory_job)


def report_worker_handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    """Lambda handler for report generation SQS events."""
    return _handle_sqs_jobs(event, _process_report_job)


def _handle_sqs_jobs(
    event: dict[str, Any],
    processor: Callable[[WorkerJob], dict[str, Any]],
    *,
    idempotency_store: Any | None = None,
) -> dict[str, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    store = idempotency_store or _job_idempotency_store()

    for message_id, job in parse_sqs_event(event):
        started = store.start_job(job.job_id, job_type=job.job_type)
        if not started.started:
            continue
        if not started.claim_token:
            raise RuntimeError(f"idempotency store claimed {job.job_id} without a claim token")
        try:
            result = processor(job)
        except Exception as exc:
            try:
                store.mark_failed(job.job_id, claim_token=started.claim_token, error=str(exc))
            except IdempotencyClaimLost:
                pass
            failures.append({"itemIdentifier": message_id})
        else:
            try:
                store.mark_succeeded(job.job_id, claim_token=started.claim_token, result=result)
            except IdempotencyClaimLost:
                pass
    return {"batchItemFailures": failures}


def _process_slack_poll_job(job: WorkerJob) -> dict[str, Any]:
    if not isinstance(job, SlackPollJob):
        raise TypeError(f"unsupported poll job: {job.job_type}")
    settings = load_settings()
    if not settings.slack_bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN is required for Slack poll jobs")

    with TailwagMemoryClient.from_env() as memory_client:
        state_store = _slack_state_store()
        slack_client = SlackWebApiClient(settings.slack_bot_token, include_email=job.include_email)
        poller = SlackMemoryPoller(
            slack_client,
            memory_client,
            state_store,
            retention_class=job.retention_class,
            active_thread_hours=job.active_thread_hours,
        )
        result = poller.poll_once(
            job.channel,
            backfill_hours=job.backfill_hours,
            force_backfill=job.force_backfill,
            history_limit=job.history_limit,
            reply_limit=job.reply_limit,
            extract_memory=job.extract_memory,
            enqueue_memory_extraction=job.enqueue_memory_extraction,
        )

    return {
        "channel": result.channel,
        "checked_threads": result.checked_threads,
        "ingested_threads": result.ingested_threads,
        "ingested_episode_ids": result.ingested_episode_ids,
        "queued_memory_jobs": [
            record.memory_extraction_job_id
            for record in result.episode_records
            if record.memory_extraction_job_id
        ],
    }


def _process_memory_job(job: WorkerJob) -> dict[str, Any]:
    if not isinstance(
        job,
        MemoryExtractEpisodeJob | MemoryConsolidatePersonJob | MemoryConsolidateAllJob | RelayMaintenanceJob,
    ):
        raise TypeError(f"unsupported memory job: {job.job_type}")
    with TailwagMemoryClient.from_env() as client:
        if isinstance(job, MemoryExtractEpisodeJob):
            result = client.extract_memory_for_episode(job.episode_id, person_id=job.person_id)
        elif isinstance(job, MemoryConsolidatePersonJob):
            result = client.consolidate_memory(
                person_id=job.person_id,
                **_consolidation_kwargs(job),
            )
        elif isinstance(job, MemoryConsolidateAllJob):
            result = client.consolidate_memory(
                all_people=True,
                person_limit=job.person_limit,
                **_consolidation_kwargs(job),
            )
        else:
            result = _relay_message_service(client.runner).run_maintenance(
                now=job.now,
                claim_timeout_seconds=job.claim_timeout_seconds,
            )
    return _plain_result(result)


def _process_report_job(job: WorkerJob) -> dict[str, Any]:
    if not isinstance(job, ReportGenerateJob):
        raise TypeError(f"unsupported report job: {job.job_type}")
    bucket = os.getenv("TAILWAG_REPORTS_BUCKET")
    if not bucket:
        raise RuntimeError("TAILWAG_REPORTS_BUCKET is required for report jobs")
    with TailwagMemoryClient.from_env() as client:
        files = render_report_files(
            client.runner,
            reports=job.reports,
            person_id=job.person_id,
            limit=job.limit,
            include_assets=job.include_assets,
        )
    published = publish_report_files(
        _boto3_client("s3"),
        bucket=bucket,
        output_prefix=job.output_prefix,
        files=files,
    )
    return {"published": [asdict(item) for item in published]}


def _consolidation_kwargs(job: MemoryConsolidatePersonJob | MemoryConsolidateAllJob) -> dict[str, int]:
    kwargs: dict[str, int] = {}
    for name in ["min_evidence_episodes", "seed_limit", "neighbor_limit", "cluster_limit", "episode_text_limit"]:
        value = getattr(job, name)
        if value is not None:
            kwargs[name] = value
    return kwargs


def _plain_result(result: object) -> dict[str, Any]:
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {"result": result}


def _slack_state_store() -> Any:
    table_name = os.getenv("TAILWAG_SLACK_POLL_STATE_TABLE")
    if not table_name:
        raise RuntimeError("TAILWAG_SLACK_POLL_STATE_TABLE is required for Slack poll jobs")
    from .slack_state import SlackDynamoDBPollStateStore

    return SlackDynamoDBPollStateStore(_boto3_resource("dynamodb").Table(table_name))


def _relay_message_service(runner: Any) -> Any:
    from tailwag_memory.relay_messages import RelayMessageService

    return RelayMessageService(runner)


def _job_idempotency_store() -> DynamoDBJobIdempotencyStore:
    table_name = os.getenv("TAILWAG_JOB_IDEMPOTENCY_TABLE")
    if not table_name:
        raise RuntimeError("TAILWAG_JOB_IDEMPOTENCY_TABLE is required for AWS workers")
    lease_seconds = int(os.getenv("TAILWAG_JOB_LEASE_SECONDS", "900"))
    return DynamoDBJobIdempotencyStore(
        _boto3_resource("dynamodb").Table(table_name),
        lease_seconds=lease_seconds,
    )


def _boto3_client(service_name: str) -> Any:
    import boto3

    return boto3.client(service_name)


def _boto3_resource(service_name: str) -> Any:
    import boto3

    return boto3.resource(service_name)
