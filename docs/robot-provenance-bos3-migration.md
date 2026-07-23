# Robot Provenance And BOS3 Migration Runbook

## Purpose

This runbook coordinates the Tailwag Robot schema release, the Argos live
episode adapter release, canonical BOS3 site-place migration, directory
home-base links, and the historical Cody Argos conversation episode backfill.

The database mutation is manual. Run the exact preflight, mutation, and
postflight below in one interactive cypher-shell transaction. Do not run the
mutation through an auto-commit browser or as separate transactions.

The currently documented development target is AWS account 032318240470,
region us-east-2. Re-verify all resource identifiers at execution time. This
release changes the Tailwag API image, Neo4j schema/data, and separately
deployed Argos code/configuration. It does not require CloudFormation, API
Gateway, VPC, IAM, secret, environment-variable, or Lambda worker-package
changes.

## Non-negotiable gates

- Both repositories are committed and reviewed on branch schema-updates.
- Every graph writer is paused for the AWS backup, migration, and deployments.
- The exact Cypher below passes first against an isolated local Neo4j 5.26
  rehearsal database populated from an approved, access-controlled dump of the
  actual source environment.
- The AWS preflight passes before any AWS mutation.
- Mutation and postflight run in one explicit transaction; postflight must pass
  before commit.
- A mutation that returns no row is rolled back.
- The Argos conversation backfill is never rerun after updated Argos resumes.

## 1. Validate both releases

Tailwag:

~~~bash
git branch --show-current
git status --short
git log -1 --oneline
PYTHONPATH=src python3 -m unittest discover -s tests
~~~

Argos:

~~~bash
cd ../argos-agent
git branch --show-current
git status --short
git log -1 --oneline
source setup_shell.sh
python3 -B -m pytest \
  tests/argos_src/provider_api \
  tests/argos_src/identity_memory \
  tests/argos_src/agent/test_agent_runtime.py \
  tests/argos_src/test_argos_profile_config.py \
  tests/scripts/labs/test_enrollment_collection_common.py
~~~

Both branches must be schema-updates. Commit and review the exact release
changes, then record both immutable SHAs in the operator log.

## 2. Rehearse against a local copy before AWS

The repository defines Neo4j 5.26 in docker-compose.yml, but it does not define
an approved AWS database-export/data-transfer procedure. Obtain a current,
approved, access-controlled dump using the organization's existing procedure.
Do not put the dump in either repository. Record its source environment,
timestamp, episode, BOS3 Place, BOS3 directory, Cody node, and existing robot
relationship counts.

Do not proceed to AWS if an approved representative copy of the actual source
environment cannot be obtained. A synthetic fixture may supplement edge-case
testing, but it does not replace this required rehearsal. The repositories do
not currently define the approved export, transfer, owner, or restore commands;
record that external procedure in the operator log before starting this step.

Restore the approved dump into an isolated local Neo4j 5.26 instance. Make sure
ports 7474 and 7687 point only to that local rehearsal instance. Install the
reviewed Tailwag version and initialize the schema:

~~~bash
docker compose up -d neo4j
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=tailwag-memory
PYTHONPATH=src python3 -m tailwag_memory.cli schema init
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER"
~~~

If the installed CLI entry point is used instead, tailwag schema init is
equivalent. At the cypher-shell prompt, run steps 5 through 8 exactly as
written below. Confirm all preflight and postflight gates, commit the local
transaction, and save the outputs.

Then discard and restore the rehearsal database from the same pristine dump.
Run the exact transaction a second time. This proves that the documented
procedure works from the intended pre-migration state. Do not attempt to prove
idempotence by rerunning the Argos conversation backfill on an already migrated
database; the Cody-node and eligible-link guards must block that rerun.

Also rehearse rollback once: restore the pristine dump, begin the transaction,
run the mutation, run :rollback, and verify the preflight counts are unchanged.
Only after both the commit rehearsal and rollback rehearsal pass may the AWS
maintenance window begin.

## 3. Verify AWS identity and inventory

~~~bash
export AWS_REGION=us-east-2
export AWS_ACCOUNT_ID_EXPECTED=032318240470
export ECS_CLUSTER=aaggarwal1-tailwag-cluster
export ECS_SERVICE=aaggarwal1-tailwag-api-service
export ECS_TASK_FAMILY=aaggarwal1-tailwag-api-task
export ECR_REPOSITORY=aaggarwal1-tailwag-dev-api
export NEO4J_INSTANCE_ID=i-0ad802133b18b8655
export NEO4J_DATA_VOLUME_ID=vol-08fc243d588cd2cd9

aws sts get-caller-identity
aws configure get region
test "$(aws sts get-caller-identity --query Account --output text)" = "$AWS_ACCOUNT_ID_EXPECTED"

aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --instance-ids "$NEO4J_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{state:State.Name,privateIp:PrivateIpAddress,volumes:BlockDeviceMappings[].Ebs.VolumeId}'

aws ec2 describe-volumes \
  --region "$AWS_REGION" \
  --volume-ids "$NEO4J_DATA_VOLUME_ID" \
  --query 'Volumes[0].{state:State,encrypted:Encrypted,attachments:Attachments[].InstanceId}'

aws ecs describe-services \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --query 'services[0].{status:status,desired:desiredCount,running:runningCount,taskDefinition:taskDefinition}'
~~~

Stop if account, region, volume ownership/encryption, or service identity differs
from the reviewed inventory.

## 4. Pause writers and take a recoverable backup

Record the active ECS task definition and desired count:

~~~bash
export PREVIOUS_TASK_DEFINITION_ARN="$(aws ecs describe-services \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --query 'services[0].taskDefinition' \
  --output text)"

export PREVIOUS_ECS_DESIRED_COUNT="$(aws ecs describe-services \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --query 'services[0].desiredCount' \
  --output text)"
~~~

Pause Argos first and record its deployed revision and resume command. There is
no Tailwag-owned scheduled employee-directory sync in this repository; discover
and pause any external directory sync.

Scale the Tailwag API to zero:

~~~bash
aws ecs update-service \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --desired-count 0 >/dev/null

aws ecs wait services-stable \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE"
~~~

Record all event-source mapping UUIDs and states for the poll, memory, and report
workers:

~~~bash
aws lambda list-event-source-mappings \
  --region "$AWS_REGION" \
  --function-name aaggarwal1-tailwag-dev-poll-worker

aws lambda list-event-source-mappings \
  --region "$AWS_REGION" \
  --function-name aaggarwal1-tailwag-dev-memory-worker

aws lambda list-event-source-mappings \
  --region "$AWS_REGION" \
  --function-name aaggarwal1-tailwag-dev-report-worker
~~~

Disable each enabled mapping and wait for Disabled:

~~~bash
aws lambda update-event-source-mapping \
  --region "$AWS_REGION" \
  --uuid <mapping-uuid> \
  --no-enabled
~~~

Do not purge queues; scheduled messages may wait during maintenance.

Stop Neo4j, snapshot its encrypted data volume, verify completion, and restart:

~~~bash
aws ec2 stop-instances \
  --region "$AWS_REGION" \
  --instance-ids "$NEO4J_INSTANCE_ID" >/dev/null

aws ec2 wait instance-stopped \
  --region "$AWS_REGION" \
  --instance-ids "$NEO4J_INSTANCE_ID"

export MIGRATION_SNAPSHOT_ID="$(aws ec2 create-snapshot \
  --region "$AWS_REGION" \
  --volume-id "$NEO4J_DATA_VOLUME_ID" \
  --description 'Tailwag pre Robot provenance and BOS3 migration' \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Name,Value=tailwag-pre-robot-bos3-migration},{Key=Purpose,Value=pre-migration-backup}]' \
  --query SnapshotId \
  --output text)"

aws ec2 wait snapshot-completed \
  --region "$AWS_REGION" \
  --snapshot-ids "$MIGRATION_SNAPSHOT_ID"

aws ec2 describe-snapshots \
  --region "$AWS_REGION" \
  --snapshot-ids "$MIGRATION_SNAPSHOT_ID" \
  --query 'Snapshots[0].{id:SnapshotId,state:State,encrypted:Encrypted,volume:VolumeId,start:StartTime}'

aws ec2 start-instances \
  --region "$AWS_REGION" \
  --instance-ids "$NEO4J_INSTANCE_ID" >/dev/null

aws ec2 wait instance-status-ok \
  --region "$AWS_REGION" \
  --instance-ids "$NEO4J_INSTANCE_ID"
~~~

Require a completed encrypted snapshot of the expected volume and record its ID
outside the repository.

Open an SSM Bolt tunnel, retrieve the password without printing it, initialize
the new schema, and connect with cypher-shell:

~~~bash
aws ssm start-session \
  --region "$AWS_REGION" \
  --target "$NEO4J_INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7687"],"localPortNumber":["7687"]}'
~~~

In a second terminal:

~~~bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD="$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION" \
  --secret-id aaggarwal1-tailwag/neo4j-password \
  --query SecretString \
  --output text)"
tailwag schema init
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER"
~~~

Supply the password at the prompt rather than as a command-line argument.

## 5. Verify required constraints

Run locally during rehearsal and again against AWS:

~~~cypher
SHOW CONSTRAINTS
YIELD name, type, labelsOrTypes, properties
WHERE type = 'UNIQUENESS'
  AND (
    (labelsOrTypes = ['Robot'] AND properties = ['id'])
    OR (labelsOrTypes = ['Place'] AND properties = ['building_code', 'room_id'])
    OR (labelsOrTypes = ['EmployeeDirectoryRecord'] AND properties = ['site_code', 'username'])
  )
RETURN name, type, labelsOrTypes, properties
ORDER BY labelsOrTypes[0];
~~~

Require exactly three uniqueness constraints, one for each listed label/property
set.

## 6. Begin and run preflight

~~~cypher
:begin
~~~

~~~cypher
CALL () {
  MATCH (site:Place {building_code: 'BOS3'})
  RETURN count(site) AS bos3_place_count,
         collect({room_id: site.room_id, element_id: elementId(site)}) AS bos3_places
}
CALL () {
  MATCH (directory:EmployeeDirectoryRecord {site_code: 'BOS3'})
  RETURN count(directory) AS bos3_directory_records
}
CALL () {
  MATCH (episode:Episode)
  RETURN count(episode) AS all_episode_count,
         count(CASE
           WHEN episode.id STARTS WITH 'argos:conversation:'
            AND episode.episode_type = 'conversation'
           THEN 1
         END) AS eligible_argos_conversation_count,
         count(CASE
           WHEN NOT coalesce(
             episode.id STARTS WITH 'argos:conversation:'
             AND episode.episode_type = 'conversation',
             false
           )
           THEN 1
         END) AS excluded_episode_count,
         count(CASE
           WHEN episode.id STARTS WITH 'argos:conversation:'
            AND coalesce(episode.episode_type, '') <> 'conversation'
           THEN 1
         END) AS malformed_argos_episode_count
}
CALL () {
  OPTIONAL MATCH (robot:Robot {id: 'cody'})
  RETURN count(robot) AS cody_node_count,
         collect(robot.display_name) AS cody_names
}
CALL () {
  OPTIONAL MATCH (:Robot)-[rel:PARTICIPATED_IN]->(episode:Episode)
  RETURN count(CASE
           WHEN episode.id STARTS WITH 'argos:conversation:'
            AND episode.episode_type = 'conversation'
           THEN rel
         END) AS existing_robot_eligible_links,
         count(CASE
           WHEN rel IS NOT NULL AND NOT coalesce(
             episode.id STARTS WITH 'argos:conversation:'
             AND episode.episode_type = 'conversation',
             false
           )
           THEN rel
         END) AS existing_robot_excluded_links
}
CALL () {
  MATCH (directory:EmployeeDirectoryRecord {site_code: 'BOS3'})
  OPTIONAL MATCH (directory)-[home:HOME_BASED_AT]->()
  RETURN count(home) AS existing_home_base_links,
         count(DISTINCT CASE WHEN home IS NOT NULL THEN directory END)
           AS directories_with_home_base
}
CALL () {
  OPTIONAL MATCH (:Person)-[rel:HOME_BASED_AT]->()
  RETURN count(rel) AS existing_person_home_base_links
}
CALL () {
  OPTIONAL MATCH (robot:Robot)-[rel]-(target)
  WHERE rel IS NOT NULL
    AND NOT EXISTS {
      MATCH (robot)-[allowed:PARTICIPATED_IN]->(target:Episode)
      WHERE allowed = rel
    }
  RETURN count(rel) AS unexpected_robot_relationships
}
RETURN bos3_place_count,
       bos3_places,
       bos3_directory_records,
       existing_home_base_links,
       directories_with_home_base,
       all_episode_count,
       eligible_argos_conversation_count,
       excluded_episode_count,
       malformed_argos_episode_count,
       cody_node_count,
       cody_names,
       existing_robot_eligible_links,
       existing_robot_excluded_links,
       existing_person_home_base_links,
       unexpected_robot_relationships;
~~~

Proceed only when:

- bos3_place_count is 1.
- bos3_directory_records and eligible_argos_conversation_count are both greater
  than zero.
- malformed_argos_episode_count is 0. Review and record
  all_episode_count, eligible_argos_conversation_count, excluded_episode_count,
  and existing_robot_excluded_links before proceeding.
- cody_node_count is 0. This durable node-existence gate prevents a later
  rerun even if old episode re-ingestion removes every Cody relationship.
- existing_robot_eligible_links is 0.
- existing_person_home_base_links and unexpected_robot_relationships are 0.
- Existing home-base links have been reviewed.
- Step 5 returned exactly the three required constraints.

Otherwise run :rollback.

## 7. Run the single guarded mutation

~~~cypher
WITH toString(datetime()) AS written_at
MATCH (candidate:Place {building_code: 'BOS3'})
WITH written_at, collect(candidate) AS candidates
WHERE size(candidates) = 1
WITH written_at, candidates[0] AS site
CALL () {
  MATCH (directory:EmployeeDirectoryRecord {site_code: 'BOS3'})
  RETURN count(directory) AS directory_count
}
CALL () {
  MATCH (episode:Episode)
  WHERE episode.id STARTS WITH 'argos:conversation:'
    AND episode.episode_type = 'conversation'
  RETURN count(episode) AS eligible_episode_count
}
CALL () {
  OPTIONAL MATCH (robot:Robot {id: 'cody'})
  RETURN count(robot) AS cody_node_count
}
CALL () {
  OPTIONAL MATCH (:Robot)-[rel:PARTICIPATED_IN]->(episode:Episode)
  WHERE episode.id STARTS WITH 'argos:conversation:'
    AND episode.episode_type = 'conversation'
  RETURN count(rel) AS existing_robot_eligible_links
}
CALL () {
  OPTIONAL MATCH (:Person)-[rel:HOME_BASED_AT]->()
  RETURN count(rel) AS existing_person_home_base_links
}
CALL () {
  OPTIONAL MATCH (robot:Robot)-[rel]-(target)
  WHERE rel IS NOT NULL
    AND NOT EXISTS {
      MATCH (robot)-[allowed:PARTICIPATED_IN]->(target:Episode)
      WHERE allowed = rel
    }
  RETURN count(rel) AS unexpected_robot_relationships
}
WITH written_at, site, directory_count, eligible_episode_count,
     cody_node_count, existing_robot_eligible_links,
     existing_person_home_base_links, unexpected_robot_relationships
WHERE directory_count > 0
  AND eligible_episode_count > 0
  AND cody_node_count = 0
  AND existing_robot_eligible_links = 0
  AND existing_person_home_base_links = 0
  AND unexpected_robot_relationships = 0
OPTIONAL MATCH (collision:Place {building_code: 'BOS3', room_id: '__site__'})
WITH written_at, site, directory_count, eligible_episode_count, collision
WHERE collision IS NULL OR collision = site
SET site.room_id = '__site__'
WITH written_at, site, directory_count, eligible_episode_count
CALL (site) {
  MATCH (directory:EmployeeDirectoryRecord {site_code: 'BOS3'})
  CALL (directory) {
    MATCH (directory)-[old:HOME_BASED_AT]->()
    DELETE old
  }
  MERGE (directory)-[:HOME_BASED_AT]->(site)
  RETURN count(directory) AS directory_records_linked
}
WITH written_at, site, directory_count, eligible_episode_count,
     directory_records_linked
WHERE directory_records_linked = directory_count
MERGE (robot:Robot {id: 'cody'})
ON CREATE SET robot.created_at = written_at
SET robot.display_name = 'Cody',
    robot.created_at = coalesce(robot.created_at, written_at),
    robot.updated_at = written_at
WITH site, eligible_episode_count, directory_records_linked, robot
MATCH (episode:Episode)
WHERE episode.id STARTS WITH 'argos:conversation:'
  AND episode.episode_type = 'conversation'
MERGE (robot)-[participation:PARTICIPATED_IN]->(episode)
ON CREATE SET participation.display_name_at_time = 'Cody'
SET participation.role = 'host',
    participation.source = 'argos'
RETURN site.building_code AS site_code,
       site.room_id AS canonical_room_id,
       directory_records_linked,
       eligible_episode_count AS expected_episodes,
       count(DISTINCT episode) AS episodes_linked,
       robot.id AS robot_id,
       robot.display_name AS robot_display_name;
~~~

Require exactly one row with BOS3, __site__, matching the preflight directory
and eligible Argos conversation counts, and cody/Cody. No row means a guard
failed; run :rollback.

## 8. Run postflight before commit

~~~cypher
CALL () {
  MATCH (site:Place {building_code: 'BOS3'})
  RETURN count(site) AS bos3_place_count,
         count(CASE WHEN site.room_id = '__site__' THEN 1 END)
           AS canonical_bos3_places
}
CALL () {
  MATCH (directory:EmployeeDirectoryRecord {site_code: 'BOS3'})
  RETURN count(directory) AS directory_records
}
CALL () {
  MATCH (directory:EmployeeDirectoryRecord {site_code: 'BOS3'})
  OPTIONAL MATCH (directory)-[home:HOME_BASED_AT]->(target)
  RETURN count(home) AS home_base_relationships,
         count(DISTINCT CASE
           WHEN target.building_code = 'BOS3' AND target.room_id = '__site__'
           THEN directory
         END) AS correctly_linked_directory_records,
         count(CASE
           WHEN home IS NOT NULL
            AND NOT coalesce(
              target:Place
              AND target.building_code = 'BOS3'
              AND target.room_id = '__site__',
              false
            )
           THEN 1
         END) AS wrong_home_base_relationships
}
CALL () {
  OPTIONAL MATCH (:Person)-[rel:HOME_BASED_AT]->()
  RETURN count(rel) AS person_home_base_relationships
}
CALL () {
  MATCH (episode:Episode)
  RETURN count(episode) AS all_episodes,
         count(CASE
           WHEN episode.id STARTS WITH 'argos:conversation:'
            AND episode.episode_type = 'conversation'
           THEN 1
         END) AS eligible_argos_conversations,
         count(CASE
           WHEN NOT coalesce(
             episode.id STARTS WITH 'argos:conversation:'
             AND episode.episode_type = 'conversation',
             false
           )
           THEN 1
         END) AS excluded_episodes
}
CALL () {
  OPTIONAL MATCH (robot:Robot {id: 'cody'})
  RETURN count(robot) AS cody_nodes,
         collect(robot.display_name) AS cody_names
}
CALL () {
  OPTIONAL MATCH (:Robot {id: 'cody'})-[rel:PARTICIPATED_IN]->(episode:Episode)
  RETURN count(CASE
           WHEN episode.id STARTS WITH 'argos:conversation:'
            AND episode.episode_type = 'conversation'
           THEN rel
         END) AS cody_eligible_relationships,
         count(DISTINCT CASE
           WHEN episode.id STARTS WITH 'argos:conversation:'
            AND episode.episode_type = 'conversation'
           THEN episode
         END) AS cody_eligible_episodes,
         count(CASE
           WHEN rel IS NOT NULL AND NOT coalesce(
             episode.id STARTS WITH 'argos:conversation:'
             AND episode.episode_type = 'conversation',
             false
           )
           THEN rel
         END) AS cody_excluded_relationships,
         count(CASE
           WHEN rel IS NOT NULL AND NOT coalesce(
             rel.role = 'host'
             AND rel.source = 'argos'
             AND rel.display_name_at_time = 'Cody',
             false
           )
           THEN 1
         END) AS invalid_cody_relationships
}
CALL () {
  MATCH (episode:Episode)
  WHERE episode.id STARTS WITH 'argos:conversation:'
    AND episode.episode_type = 'conversation'
    AND NOT EXISTS {
    MATCH (:Robot {id: 'cody'})-[rel:PARTICIPATED_IN]->(episode)
    WHERE rel.role = 'host'
      AND rel.source = 'argos'
      AND rel.display_name_at_time = 'Cody'
  }
  RETURN count(episode) AS eligible_episodes_missing_valid_cody
}
CALL () {
  OPTIONAL MATCH (:Robot)-[rel:PARTICIPATED_IN]->(episode:Episode)
  WHERE episode.id STARTS WITH 'argos:conversation:'
    AND episode.episode_type = 'conversation'
  RETURN count(rel) AS all_eligible_robot_relationships
}
CALL () {
  OPTIONAL MATCH (robot:Robot)-[rel]-(target)
  WHERE rel IS NOT NULL
    AND NOT EXISTS {
      MATCH (robot)-[allowed:PARTICIPATED_IN]->(target:Episode)
      WHERE allowed = rel
    }
  RETURN count(rel) AS unexpected_robot_relationships
}
RETURN bos3_place_count,
       canonical_bos3_places,
       directory_records,
       home_base_relationships,
       correctly_linked_directory_records,
       wrong_home_base_relationships,
       person_home_base_relationships,
       all_episodes,
       eligible_argos_conversations,
       excluded_episodes,
       cody_nodes,
       cody_names,
       cody_eligible_relationships,
       cody_eligible_episodes,
       cody_excluded_relationships,
       invalid_cody_relationships,
       eligible_episodes_missing_valid_cody,
       all_eligible_robot_relationships,
       unexpected_robot_relationships;
~~~

Commit only when:

- bos3_place_count and canonical_bos3_places are both 1.
- directory_records, home_base_relationships, and
  correctly_linked_directory_records are equal.
- wrong_home_base_relationships and person_home_base_relationships are 0.
- cody_nodes is 1 and cody_names contains only Cody.
- eligible_argos_conversations, cody_eligible_relationships,
  cody_eligible_episodes, and all_eligible_robot_relationships are equal.
- cody_excluded_relationships, invalid_cody_relationships, and
  eligible_episodes_missing_valid_cody are 0.
- unexpected_robot_relationships is 0.

Then run :commit. Otherwise run :rollback. After commit, rerun postflight as a
read-only auto-commit query and save its output.

## 9. Deploy Tailwag, then Argos

Build an immutable Tailwag API image and register a new ECS task revision using
AWS Manual Updates. Keep desired count at zero until the new revision is ready,
then restore the recorded count:

~~~bash
aws ecs update-service \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$NEW_TASK_DEFINITION_ARN" \
  --desired-count "$PREVIOUS_ECS_DESIRED_COUNT" \
  --force-new-deployment >/dev/null

aws ecs wait services-stable \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE"
~~~

Run health checks and an old-format episode payload without `robots`, using a
brand-new unique episode ID that has never been ingested or backfilled. It must
remain valid, and only that new episode must have no Robot relationship. Never
reuse a migrated episode for this check because re-ingestion intentionally
reconciles an omitted robot list by removing existing robot links. The smoke ID
must not start with `argos:conversation:`; that namespace is reserved for live
Argos conversations and is the historical migration eligibility boundary. No
worker ZIP deploy is needed because worker entrypoints did not change.

Deploy the reviewed Argos SHA while Argos is still paused. Confirm the active
profile resolves its manifest robot ID/display name, BOS3, __site__, the existing
memory.episodes capability, and memory.episodes_record operation. Resume one
instance, record one controlled live episode, and verify exactly one existing
Tailwag request and one manifest robot attribution.

Re-enable each recorded Lambda mapping:

~~~bash
aws lambda update-event-source-mapping \
  --region "$AWS_REGION" \
  --uuid <mapping-uuid> \
  --enabled
~~~

Wait for Enabled, inspect queue depth and DLQs, resume any separately discovered
directory sync, then resume remaining Argos instances.

## 10. Final acceptance and rollback

Record the controlled post-deployment episode ID and its expected manifest Robot
ID, then inspect it by stable IDs rather than display names:

~~~cypher
:param controlled_episode_id => 'replace-with-controlled-episode-id';
:param expected_robot_id => 'replace-with-manifest-robot-id';

MATCH (episode:Episode {id: $controlled_episode_id})
OPTIONAL MATCH (robot:Robot)-[participation:PARTICIPATED_IN]->(episode)
OPTIONAL MATCH (episode)-[:OCCURRED_AT]->(place:Place)
RETURN episode.id AS episode_id,
       place.building_code AS building_code,
       place.room_id AS room_id,
       collect({
         robot_id: robot.id,
         current_display_name: robot.display_name,
         display_name_at_time: participation.display_name_at_time,
         role: participation.role,
         source: participation.source
       }) AS robots;
~~~

Require one row, `building_code='BOS3'`, `room_id='__site__'`, and exactly one
robot map whose `robot_id=$expected_robot_id`, `role='host'`, and
`source='argos'`. Confirm the provider telemetry contains exactly one
`memory.episodes_record` request for this controlled episode.

Confirm relationship boundaries after all writers resume:

~~~cypher
CALL () {
  OPTIONAL MATCH (:Person)-[rel:HOME_BASED_AT]->()
  RETURN count(rel) AS person_home_base_relationships
}
CALL () {
  OPTIONAL MATCH (robot:Robot)-[rel]-(target)
  WHERE rel IS NOT NULL
    AND NOT EXISTS {
      MATCH (robot)-[allowed:PARTICIPATED_IN]->(target:Episode)
      WHERE allowed = rel
    }
  RETURN count(rel) AS unexpected_robot_relationships
}
RETURN person_home_base_relationships, unexpected_robot_relationships;
~~~

Both counts must be zero. Verify rename/current-name versus historical-snapshot
behavior against the isolated local rehearsal database, not by renaming a live
deployed Robot. The Tailwag regression checks are:

~~~bash
PYTHONPATH=src python3 -m unittest tests.test_ingestion tests.test_retrieval
~~~

Before commit, rollback is :rollback. After commit, pause writers again before
any application rollback. Prefer a forward fix and leave the additive Robot
constraint/data and canonical site links in place. Restoring the EBS snapshot
would destroy every graph write after the snapshot and requires separate
explicit approval, a confirmed target volume/instance, and reconciliation of
post-snapshot caller activity; this runbook does not authorize an automatic EBS
swap or deletion.
