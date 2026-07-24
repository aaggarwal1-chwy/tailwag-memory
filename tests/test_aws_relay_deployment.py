from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from tailwag_memory.aws.jobs import RelayMaintenanceJob, parse_job_payload


ROOT = Path(__file__).resolve().parents[1]
AWS_DEPLOY = ROOT / "deploy" / "aws"
ROBOT_TOKEN_ENV = "TAILWAG_ROBOT_API_TOKENS_JSON"
ROBOT_TOKEN_SECRET = "<complete-robot-api-tokens-json-secret-arn-from-describe-secret>"
ATTESTATION_SECRET_ENV = "TAILWAG_RELAY_ATTESTATION_SECRET"
ATTESTATION_SECRET = "<complete-relay-attestation-secret-arn-from-describe-secret>"


def _yaml_mapping_block(document: str, key: str, *, indentation: int = 2) -> str:
    """Return one mapping block without requiring a CloudFormation YAML loader."""
    lines = document.splitlines()
    header = f"{' ' * indentation}{key}:"
    try:
        start = lines.index(header)
    except ValueError as exc:
        raise AssertionError(f"missing YAML mapping {key}") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and len(line) - len(line.lstrip()) <= indentation:
            end = index
            break
    return "\n".join(lines[start:end])


class AwsRelayDeploymentContractTest(unittest.TestCase):
    def test_edge_integration_uses_thirty_second_timeout_parameter(self) -> None:
        template = (AWS_DEPLOY / "cloudformation" / "tailwag-memory-edge.yaml").read_text()
        timeout_parameter = _yaml_mapping_block(template, "IntegrationTimeoutInMillis")
        integration = _yaml_mapping_block(template, "TailwagPrivateIntegration")

        self.assertRegex(timeout_parameter, r"(?m)^\s+Default:\s+30000$")
        self.assertRegex(timeout_parameter, r"(?m)^\s+MaxValue:\s+30000$")
        self.assertRegex(
            integration,
            r"(?m)^\s+TimeoutInMillis:\s+!Ref IntegrationTimeoutInMillis$",
        )

    def test_robot_tokens_are_injected_from_secret_not_plaintext_environment(self) -> None:
        task = json.loads((ROOT / "deploy" / "ecs-task-definition.example.json").read_text())
        container = task["containerDefinitions"][0]
        environment = {item["name"]: item["value"] for item in container["environment"]}
        secrets = {item["name"]: item for item in container["secrets"]}

        self.assertNotIn(ROBOT_TOKEN_ENV, environment)
        self.assertEqual(
            secrets[ROBOT_TOKEN_ENV],
            {"name": ROBOT_TOKEN_ENV, "valueFrom": ROBOT_TOKEN_SECRET},
        )

        execution_policy = json.loads(
            (AWS_DEPLOY / "iam" / "tailwag-api-execution-role-policy.example.json").read_text()
        )
        secret_statement = next(
            statement
            for statement in execution_policy["Statement"]
            if statement["Sid"] == "ReadTailwagRuntimeSecrets"
        )
        self.assertIn(ROBOT_TOKEN_SECRET, secret_statement["Resource"])

        deployment_env = {
            key: value
            for key, value in (
                line.split("=", 1)
                for line in (AWS_DEPLOY / "deployment.env.example").read_text().splitlines()
                if line and not line.startswith("#")
            )
        }
        self.assertNotIn(ROBOT_TOKEN_ENV, deployment_env)
        self.assertEqual(
            deployment_env["TAILWAG_ROBOT_API_TOKENS_SECRET_ID"],
            "aaggarwal1-tailwag/robot-api-tokens-json",
        )

    def test_relay_attestation_secret_uses_existing_ecs_secret_injection_pattern(self) -> None:
        task = json.loads((ROOT / "deploy" / "ecs-task-definition.example.json").read_text())
        container = task["containerDefinitions"][0]
        environment = {item["name"]: item["value"] for item in container["environment"]}
        secrets = {item["name"]: item for item in container["secrets"]}

        self.assertNotIn(ATTESTATION_SECRET_ENV, environment)
        self.assertEqual(
            secrets[ATTESTATION_SECRET_ENV],
            {"name": ATTESTATION_SECRET_ENV, "valueFrom": ATTESTATION_SECRET},
        )
        self.assertEqual(
            environment["TAILWAG_RELAY_ATTESTATION_KEY_ID"],
            "relay-signing-2026-07",
        )

        execution_policy = json.loads(
            (AWS_DEPLOY / "iam" / "tailwag-api-execution-role-policy.example.json").read_text()
        )
        secret_statement = next(
            statement
            for statement in execution_policy["Statement"]
            if statement["Sid"] == "ReadTailwagRuntimeSecrets"
        )
        self.assertIn(ATTESTATION_SECRET, secret_statement["Resource"])

        deployment_env = {
            key: value
            for key, value in (
                line.split("=", 1)
                for line in (AWS_DEPLOY / "deployment.env.example").read_text().splitlines()
                if line and not line.startswith("#")
            )
        }
        self.assertEqual(
            deployment_env["TAILWAG_RELAY_ATTESTATION_SECRET_ID"],
            "aaggarwal1-tailwag/relay-attestation-secret",
        )
        self.assertEqual(
            deployment_env["TAILWAG_RELAY_ATTESTATION_KEY_ID"],
            "relay-signing-2026-07",
        )

    def test_manual_ecs_rollout_carries_required_attestation_configuration(self) -> None:
        manual = (ROOT / "docs" / "aws-manual-updates.md").read_text()
        deployment = (ROOT / "docs" / "aws-deployment.md").read_text()

        for required in (
            "TAILWAG_RELAY_ATTESTATION_SECRET_ID",
            "TAILWAG_RELAY_ATTESTATION_SECRET_ARN",
            "TAILWAG_RELAY_ATTESTATION_KEY_ID",
            'upsert_secret(\n                "TAILWAG_RELAY_ATTESTATION_SECRET"',
            'upsert_environment(\n                "TAILWAG_RELAY_ATTESTATION_KEY_ID"',
            '"$TAILWAG_RELAY_ATTESTATION_SECRET_ARN"',
            "utf8bytelength >= 32",
            "Keep the prior attestation secret available through the rollback window",
        ):
            with self.subTest(required=required):
                self.assertIn(required, manual)

        simulation_start = manual.index("test \"$(aws iam simulate-principal-policy")
        simulation_end = manual.index("\njq -e \\", simulation_start)
        simulation = manual[simulation_start:simulation_end]
        self.assertIn("--resource-arns", simulation)
        self.assertIn('"$TAILWAG_ROBOT_API_TOKENS_SECRET_ARN"', simulation)
        self.assertIn('"$TAILWAG_RELAY_ATTESTATION_SECRET_ARN"', simulation)
        self.assertIn("`/ready` must succeed", manual)

        for required in (
            "`aaggarwal1-tailwag/relay-attestation-secret`",
            "`TAILWAG_RELAY_ATTESTATION_KEY_ID`",
            "both exact secret ARNs with IAM policy simulation",
        ):
            with self.subTest(deployment_required=required):
                self.assertIn(required, deployment)
        self.assertRegex(
            deployment,
            r"Stop\s+relay traffic if `/ready` rejects the signing secret or key ID",
        )

    def test_relay_maintenance_schedule_is_disabled_and_targets_memory_dlq(self) -> None:
        schedule = json.loads(
            (AWS_DEPLOY / "scheduler" / "relay-maintenance-schedule.example.json").read_text()
        )
        target = schedule["Target"]
        payload = json.loads(target["Input"])

        self.assertEqual(schedule["State"], "DISABLED")
        self.assertEqual(schedule["FlexibleTimeWindow"], {"Mode": "OFF"})
        self.assertTrue(target["Arn"].endswith(":aaggarwal1-tailwag-dev-memory-jobs"))
        self.assertEqual(target["DeadLetterConfig"]["Arn"], f"{target['Arn']}-dlq")
        self.assertRegex(
            target["RoleArn"],
            r"^arn:aws:iam::<account-id>:role/.+-scheduler-role$",
        )
        self.assertEqual(
            target["RetryPolicy"],
            {
                "MaximumEventAgeInSeconds": 900,
                "MaximumRetryAttempts": 2,
            },
        )
        self.assertEqual(payload["job_type"], "relay_maintenance")
        self.assertEqual(payload["claim_timeout_seconds"], 120)
        self.assertIn("<aws.scheduler.execution-id>", payload["job_id"])
        self.assertEqual(
            parse_job_payload(payload),
            RelayMaintenanceJob(
                job_id=payload["job_id"],
                claim_timeout_seconds=120,
            ),
        )

        scheduler_policy = json.loads(
            (AWS_DEPLOY / "iam" / "tailwag-scheduler-policy.example.json").read_text()
        )
        scheduler_statement = scheduler_policy["Statement"][0]
        self.assertEqual(scheduler_statement["Effect"], "Allow")
        self.assertEqual(scheduler_statement["Action"], "sqs:SendMessage")
        allowed_resources = scheduler_statement["Resource"]
        self.assertIn(target["Arn"], allowed_resources)
        self.assertIn(target["DeadLetterConfig"]["Arn"], allowed_resources)

        worker_policy = json.loads(
            (AWS_DEPLOY / "iam" / "tailwag-worker-policy.example.json").read_text()
        )
        worker_actions = {
            action
            for statement in worker_policy["Statement"]
            for action in (
                [statement["Action"]]
                if isinstance(statement["Action"], str)
                else statement["Action"]
            )
        }
        self.assertTrue(
            {
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes",
            }.issubset(worker_actions)
        )

    def test_api_port_and_memory_worker_handler_match_runtime_artifacts(self) -> None:
        task = json.loads((ROOT / "deploy" / "ecs-task-definition.example.json").read_text())
        container = task["containerDefinitions"][0]
        environment = {item["name"]: item["value"] for item in container["environment"]}
        api_port = int(environment["TAILWAG_API_PORT"])

        self.assertIn(api_port, [mapping["containerPort"] for mapping in container["portMappings"]])
        self.assertIn(f"127.0.0.1:{api_port}/health", container["healthCheck"]["command"][-1])

        core = (AWS_DEPLOY / "cloudformation" / "tailwag-memory-core.yaml").read_text()
        handler_parameter = _yaml_mapping_block(core, "MemoryWorkerHandler")
        match = re.search(r"(?m)^\s+Default:\s+(\S+)$", handler_parameter)
        self.assertIsNotNone(match)
        module_name, function_name = match.group(1).rsplit(".", 1)
        self.assertTrue(callable(getattr(importlib.import_module(module_name), function_name)))

    def test_aws_json_examples_are_valid_json(self) -> None:
        examples = sorted(AWS_DEPLOY.rglob("*.json")) + [
            ROOT / "deploy" / "ecs-task-definition.example.json"
        ]
        self.assertTrue(examples)
        for example in examples:
            with self.subTest(example=example.relative_to(ROOT)):
                json.loads(example.read_text())

    @unittest.skipUnless(shutil.which("sh"), "POSIX sh is required for syntax checks")
    def test_aws_packaging_scripts_have_valid_shell_syntax(self) -> None:
        scripts = sorted((AWS_DEPLOY / "scripts").glob("*.sh"))
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.relative_to(ROOT)):
                subprocess.run(
                    ["sh", "-n", str(script)],
                    check=True,
                    capture_output=True,
                    text=True,
                )


if __name__ == "__main__":
    unittest.main()
