from __future__ import annotations

from dataclasses import asdict
from difflib import SequenceMatcher
import os
from pathlib import Path
from typing import Any, Callable

try:  # pragma: no cover - exercised when optional dependency is available.
    from rapidfuzz import fuzz as rapidfuzz_fuzz
    from rapidfuzz.distance import JaroWinkler as rapidfuzz_jaro_winkler
except Exception:  # pragma: no cover - fallback keeps tests/dev envs lightweight.
    rapidfuzz_fuzz = None
    rapidfuzz_jaro_winkler = None

from ..db import QueryRunner
from ..directory_reconciliation import person_directory_reconciliation_cypher
from ..models import (
    DirectoryPersonRecord,
    DirectorySyncResult,
    IdentityCandidate,
    IdentityResolutionResult,
    PersonProfile,
    VerifiedProfile,
    utc_now_iso,
)


EMPLOYEE_COLUMNS = (
    "EMPLOYEE_NAME",
    "BUSINESS_TITLE",
    "TIME_IN_JOB_PROFILE",
    "EMPLOYEE_USERNAME",
    "JOB_FAMILY",
    "JOB_FAMILY_GROUP",
    "JOB_LEVEL",
    "C_LEVEL",
    "MANAGER_NAME",
    "COST_CENTER",
    "SENIOR_LEADERSHIP_TEAM",
    "BUSINESS_FUNCTION",
)
EMPLOYEE_DIRECTORY_SQL = """
    SELECT
        cemp."EMPLOYEE_NAME",
        cemp."BUSINESS_TITLE",
        cemp."TIME_IN_JOB_PROFILE",
        cemp."EMPLOYEE_USERNAME",
        cemp."JOB_FAMILY",
        cemp."JOB_FAMILY_GROUP",
        cemp."JOB_LEVEL",
        cemp."C_LEVEL",
        emp."EMPLOYEE_MANAGER1_NAME" AS "MANAGER_NAME",
        cemp."COST_CENTER",
        cemp."SENIOR_LEADERSHIP_TEAM",
        cemp."BUSINESS_FUNCTION"
    FROM "EDLDB"."CHEWYBI"."CHEWYDATA_CURRENT_EMPLOYEES" cemp
    LEFT JOIN "EDLDB"."CHEWYBI"."EMPLOYEES" emp
        ON CAST(emp."EMPLOYEE_ID" AS VARCHAR) = CAST(cemp."EMPLOYEE_ID" AS VARCHAR)
    WHERE cemp."LOCATION_CODE" = %s
"""
MAX_CANDIDATES = 3
MIN_PLAUSIBLE_SCORE = 74.0
CLARIFY_SCORE = 84.0
AUTO_CONFIRM_SCORE = 98.0
CLEAR_GAP_SCORE = 5.0
MULTIPLE_MATCH_GAP = 3.0
DIRECTORY_RECORD_FIELDS = (
    "site_code",
    "official_name",
    "username",
    "employee_email",
    "business_title",
    "tenure",
    "manager_name",
    "job_family",
    "job_family_group",
    "job_level",
    "c_level",
    "cost_center",
    "senior_leadership_team",
    "business_function",
)


def load_env_file(path: Path = Path(".snowflake_env")) -> None:
    """Populate unset Snowflake environment variables from a simple env file."""
    candidates = [
        Path.cwd() / ".snowflake_env",
        path,
        Path(".env"),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        return


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connect_snowflake_from_env() -> Any:
    import snowflake.connector

    return snowflake.connector.connect(
        account=require_env("SNOWFLAKE_ACCOUNT"),
        user=require_env("SNOWFLAKE_USER"),
        password=os.environ.get("SNOWFLAKE_PASSWORD") or None,
        authenticator=os.environ.get("SNOWFLAKE_AUTHENTICATOR") or None,
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
        database=require_env("SNOWFLAKE_DATABASE"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA") or None,
    )


def employee_email_from_username(username: str, email_domain: str) -> str:
    cleaned_username = str(username or "").strip().lower()
    if not cleaned_username:
        return ""
    if "@" in cleaned_username:
        return cleaned_username
    cleaned_domain = str(email_domain or "").strip().lower().lstrip("@")
    return f"{cleaned_username}@{cleaned_domain}" if cleaned_domain else ""


def load_directory_records_from_snowflake(
    site_code: str,
    *,
    email_domain: str = "",
    env_loader: Callable[[], None] = load_env_file,
    connector_factory: Callable[[], Any] = connect_snowflake_from_env,
) -> list[DirectoryPersonRecord]:
    env_loader()
    connection = connector_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(EMPLOYEE_DIRECTORY_SQL, (str(site_code or "").strip(),))
            rows = cursor.fetchall()
            columns = [
                str(description[0] if isinstance(description, (tuple, list)) else getattr(description, "name", "")).upper()
                for description in (getattr(cursor, "description", None) or ())
            ]
        return [
            _record_from_row(
                row,
                site_code=str(site_code or "").strip(),
                email_domain=email_domain,
                columns=columns,
            )
            for row in rows
        ]
    finally:
        connection.close()


class DirectoryIdentityService:
    """Owns directory sync, lookup, and person profile projections."""

    def __init__(self, runner: QueryRunner) -> None:
        self.runner = runner

    def sync_directory_people(
        self,
        site_code: str,
        records: list[DirectoryPersonRecord] | list[dict[str, Any]],
    ) -> DirectorySyncResult:
        rendered_site = str(site_code or "").strip()
        written_at = utc_now_iso()
        normalized = []
        for record in records:
            normalized_record = _normalize_record(record, rendered_site)
            if normalized_record.username:
                normalized.append(normalized_record)
        self.runner.run(
            """
            UNWIND $records AS record
            MERGE (d:EmployeeDirectoryRecord {site_code: record.site_code, username: record.username})
            SET d.official_name = record.official_name,
                d.display_name = record.official_name,
                d.name = record.official_name,
                d.source = 'snowflake',
                d.employee_email = record.employee_email,
                d.business_title = record.business_title,
                d.job_family = record.job_family,
                d.job_family_group = record.job_family_group,
                d.job_level = record.job_level,
                d.c_level = record.c_level,
                d.manager_name = record.manager_name,
                d.cost_center = record.cost_center,
                d.senior_leadership_team = record.senior_leadership_team,
                d.business_function = record.business_function,
                d.tenure = record.tenure,
                d.normalized_name = record.normalized_name,
                d.token_sorted_name = record.token_sorted_name,
                d.updated_at = $updated_at,
                d.created_at = coalesce(d.created_at, $updated_at)
            WITH d, record
            OPTIONAL MATCH (p:Person)
            WHERE p.email IS NOT NULL
              AND p.email CONTAINS '@'
              AND toLower(split(p.email, '@')[0]) = record.username
            WITH d, record, [
              person IN collect(DISTINCT p)
              WHERE person IS NOT NULL
            ] AS people
            FOREACH (p IN people |
              SET p.official_name = CASE WHEN record.official_name <> '' THEN record.official_name ELSE p.official_name END,
                  p.display_name = CASE WHEN record.official_name <> '' THEN record.official_name ELSE p.display_name END,
                  p.name = p.id,
                  p.email = CASE WHEN record.employee_email <> '' THEN record.employee_email ELSE p.email END
              MERGE (p)-[:HAS_DIRECTORY_RECORD]->(d)
            )
            RETURN count(DISTINCT d) AS records_written
            """,
            {
                "records": [_record_payload(record) for record in normalized],
                "updated_at": written_at,
            },
        )
        return DirectorySyncResult(
            site_code=rendered_site,
            records_seen=len(records),
            records_written=len(normalized),
        )

    def sync_directory_from_snowflake(
        self,
        site_code: str,
        *,
        email_domain: str = "",
    ) -> DirectorySyncResult:
        records = load_directory_records_from_snowflake(site_code, email_domain=email_domain)
        return self.sync_directory_people(site_code, records)

    def resolve_identity(
        self,
        *,
        shared_first_name: str,
        shared_last_name: str,
        shared_name: str = "",
        site_code: str = "",
    ) -> IdentityResolutionResult:
        query_name, first_name, last_name = _build_query_identity(
            shared_first_name=shared_first_name,
            shared_last_name=shared_last_name,
            shared_name=shared_name,
        )
        if not query_name or not first_name or not last_name:
            return IdentityResolutionResult(
                success=False,
                status="invalid_input",
                message="Please provide the person's official first and last name.",
            )
        records = self._directory_records(site_code)
        if not records:
            return IdentityResolutionResult(
                success=False,
                status="directory_unavailable",
                message="The employee directory is unavailable or empty.",
            )
        candidates = _rank_candidates(query_name, records)
        if not candidates:
            return IdentityResolutionResult(
                success=False,
                status="no_match",
                message="No plausible employee match was found.",
                candidates=[],
            )
        top = candidates[0]
        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        if top.score < MIN_PLAUSIBLE_SCORE:
            return IdentityResolutionResult(
                success=False,
                status="no_match",
                message="No plausible employee match was found.",
                candidates=candidates,
            )
        if len(candidates) > 1 and top.score - runner_up <= MULTIPLE_MATCH_GAP:
            return IdentityResolutionResult(
                success=False,
                status="multiple_matches",
                message="Multiple plausible employees matched that name.",
                candidates=candidates,
            )
        if top.score < CLARIFY_SCORE or (top.score < AUTO_CONFIRM_SCORE and top.score - runner_up < CLEAR_GAP_SCORE):
            return IdentityResolutionResult(
                success=False,
                status="needs_clarification",
                message="A possible employee match was found, but confirmation is needed.",
                candidates=candidates,
            )
        return IdentityResolutionResult(
            success=True,
            status="single_match",
            message="One employee match was found.",
            data={"candidate": asdict(top)},
            candidates=[top],
        )

    def get_verified_profile(
        self,
        *,
        username: str,
        official_name: str,
        site_code: str = "",
    ) -> VerifiedProfile | None:
        rendered_username = str(username or "").strip().lower()
        rendered_name = _normalize_name(official_name)
        if not rendered_username or not rendered_name:
            return None
        rows = self.runner.run(
            f"""
            MATCH (d:EmployeeDirectoryRecord {{username: $username}})
            WHERE ($site_code = '' OR d.site_code = $site_code)
            RETURN {_directory_record_projection("d")}
            LIMIT 2
            """,
            {"username": rendered_username, "site_code": str(site_code or "").strip()},
        )
        if len(rows) != 1:
            return None
        record = _row_to_record(rows[0])
        if _normalize_name(record.official_name) != rendered_name:
            return None
        person_id = f"person_{rendered_username}"
        metadata = asdict(record)
        return VerifiedProfile(
            person_id=person_id,
            official_name=record.official_name,
            username=record.username,
            employee_email=record.employee_email,
            business_title=record.business_title,
            tenure=record.tenure,
            manager_name=record.manager_name,
            directory_profile_lines=_directory_lines(record),
            metadata=metadata,
        )

    def person_profile(self, person_id: str) -> PersonProfile | None:
        rendered = str(person_id or "").strip()
        if not rendered:
            return None
        rows = self.runner.run(
            f"""
            MATCH (p:Person {{id: $person_id}})
            OPTIONAL MATCH (p)-[:HAS_DIRECTORY_RECORD]->(d:EmployeeDirectoryRecord)
            RETURN p.id AS person_id,
                   p.display_name AS display_name,
                   p.official_name AS person_official_name,
                   p.email AS email,
                   p.consent_status AS consent_status,
                   coalesce(p.status, 'active') AS status,
                   p.interaction_count AS interaction_count,
                   p.last_seen AS last_seen,
                   {_directory_record_projection("d")}
            LIMIT 1
            """,
            {"person_id": rendered},
        )
        if not rows:
            return None
        row = rows[0]
        record = _row_to_record(row) if row.get("username") else None
        return PersonProfile(
            person_id=str(row.get("person_id") or rendered),
            display_name=_profile_display_name(row, record, rendered),
            email=str(row.get("email") or row.get("employee_email") or ""),
            consent_status=str(row.get("consent_status") or ""),
            status=str(row.get("status") or "active"),
            interaction_count=_safe_int(row.get("interaction_count")),
            last_seen=str(row.get("last_seen")) if row.get("last_seen") is not None else None,
            directory_profile_lines=_directory_lines(record) if record else (),
            metadata=dict(row),
        )

    def record_encounter(
        self,
        *,
        person_id: str,
        observed_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PersonProfile:
        rendered = str(person_id or "").strip()
        if not rendered:
            raise ValueError("person_id is required")
        now = observed_at or utc_now_iso()
        meta = dict(metadata or {})
        directory_username = _metadata_value(meta, "username").lower()
        directory_site_code = _metadata_value(meta, "site_code")
        self.runner.run(
            """
            MERGE (p:Person {id: $person_id})
            SET p.display_name = CASE
                  WHEN $official_name IS NOT NULL THEN $official_name
                  WHEN $display_name IS NOT NULL AND $display_name <> $person_id THEN $display_name
                  ELSE p.display_name
                END,
                p.official_name = coalesce($official_name, p.official_name),
                p.name = coalesce(p.name, $person_id),
                p.email = coalesce($email, p.email),
                p.consent_status = coalesce($consent_status, p.consent_status),
                p.status = coalesce(p.status, 'active'),
                p.last_seen = CASE
                  WHEN p.last_seen IS NULL OR datetime(p.last_seen) < datetime($last_seen) THEN $last_seen
                  ELSE p.last_seen
                END,
                p.interaction_count = coalesce(p.interaction_count, 0) + 1,
                p.updated_at = $updated_at,
                p.created_at = coalesce(p.created_at, $updated_at)
            """
            + person_directory_reconciliation_cypher("p")
            + """
            WITH p
            OPTIONAL MATCH (d:EmployeeDirectoryRecord {site_code: $directory_site_code, username: $directory_username})
            FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
              MERGE (p)-[:HAS_DIRECTORY_RECORD]->(d)
            )
            RETURN p.id AS person_id
            """,
            {
                "person_id": rendered,
                "display_name": _optional(meta.get("display_name") or meta.get("name")),
                "official_name": _optional(meta.get("official_name")),
                "email": _optional(meta.get("email") or meta.get("employee_email")),
                "consent_status": _optional(meta.get("consent_status")),
                "last_seen": now,
                "updated_at": now,
                "directory_username": directory_username,
                "directory_site_code": directory_site_code,
            },
        )
        profile = self.person_profile(rendered)
        if profile is None:
            return PersonProfile(person_id=rendered, display_name=rendered, last_seen=now, interaction_count=1)
        return profile

    def _directory_records(self, site_code: str) -> list[DirectoryPersonRecord]:
        rows = self.runner.run(
            f"""
            MATCH (d:EmployeeDirectoryRecord)
            WHERE ($site_code = '' OR d.site_code = $site_code)
            RETURN {_directory_record_projection("d")}
            """,
            {"site_code": str(site_code or "").strip()},
        )
        return [_row_to_record(row) for row in rows]


def _record_from_row(
    row: Any,
    *,
    site_code: str,
    email_domain: str,
    columns: list[str] | None = None,
) -> DirectoryPersonRecord:
    values_by_column = _row_values_by_column(row, columns or list(EMPLOYEE_COLUMNS))

    def value(column: str) -> str:
        return str(values_by_column.get(column, "") or "").strip()

    username = value("EMPLOYEE_USERNAME").lower()
    return DirectoryPersonRecord(
        official_name=value("EMPLOYEE_NAME"),
        business_title=value("BUSINESS_TITLE"),
        tenure=value("TIME_IN_JOB_PROFILE"),
        username=username,
        job_family=value("JOB_FAMILY"),
        job_family_group=value("JOB_FAMILY_GROUP"),
        job_level=value("JOB_LEVEL"),
        c_level=value("C_LEVEL"),
        manager_name=value("MANAGER_NAME"),
        cost_center=value("COST_CENTER"),
        senior_leadership_team=value("SENIOR_LEADERSHIP_TEAM"),
        business_function=value("BUSINESS_FUNCTION"),
        employee_email=employee_email_from_username(username, email_domain),
        site_code=site_code,
    )


def _normalize_record(record: DirectoryPersonRecord | dict[str, Any], site_code: str) -> DirectoryPersonRecord:
    if isinstance(record, DirectoryPersonRecord):
        raw = asdict(record)
    else:
        raw = dict(record)
    username = str(raw.get("username") or raw.get("employee_username") or "").strip().lower()
    return DirectoryPersonRecord(
        official_name=str(raw.get("official_name") or raw.get("employee_name") or "").strip(),
        username=username,
        site_code=str(raw.get("site_code") or site_code).strip(),
        employee_email=str(raw.get("employee_email") or raw.get("email") or "").strip().lower(),
        business_title=str(raw.get("business_title") or "").strip(),
        job_family=str(raw.get("job_family") or "").strip(),
        job_family_group=str(raw.get("job_family_group") or "").strip(),
        job_level=str(raw.get("job_level") or "").strip(),
        c_level=str(raw.get("c_level") or "").strip(),
        manager_name=str(raw.get("manager_name") or "").strip(),
        cost_center=str(raw.get("cost_center") or "").strip(),
        senior_leadership_team=str(raw.get("senior_leadership_team") or "").strip(),
        business_function=str(raw.get("business_function") or "").strip(),
        tenure=str(raw.get("tenure") or "").strip(),
    )


def _row_values_by_column(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return {str(key).upper(): value for key, value in row.items()}
    values = tuple(row)
    return {
        str(column or "").upper(): values[index]
        for index, column in enumerate(columns)
        if index < len(values)
    }


def _record_payload(record: DirectoryPersonRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["display_name"] = record.official_name
    payload["name"] = record.official_name
    payload["source"] = "snowflake"
    payload["normalized_name"] = _normalize_name(record.official_name)
    payload["token_sorted_name"] = _token_sort_key(record.official_name)
    return payload


def _row_to_record(row: dict[str, Any]) -> DirectoryPersonRecord:
    return DirectoryPersonRecord(
        official_name=str(row.get("official_name") or ""),
        username=str(row.get("username") or "").lower(),
        site_code=str(row.get("site_code") or ""),
        employee_email=str(row.get("employee_email") or ""),
        business_title=str(row.get("business_title") or ""),
        job_family=str(row.get("job_family") or ""),
        job_family_group=str(row.get("job_family_group") or ""),
        job_level=str(row.get("job_level") or ""),
        c_level=str(row.get("c_level") or ""),
        manager_name=str(row.get("manager_name") or ""),
        cost_center=str(row.get("cost_center") or ""),
        senior_leadership_team=str(row.get("senior_leadership_team") or ""),
        business_function=str(row.get("business_function") or ""),
        tenure=str(row.get("tenure") or ""),
    )


def _directory_record_projection(alias: str) -> str:
    return ",\n                   ".join(
        f"{alias}.{field} AS {field}" for field in DIRECTORY_RECORD_FIELDS
    )


def _rank_candidates(query_name: str, records: list[DirectoryPersonRecord]) -> list[IdentityCandidate]:
    ranked: list[IdentityCandidate] = []
    normalized_query = _normalize_name(query_name)
    token_query = _token_sort_key(query_name)
    for record in records:
        name_score = _score_ratio(normalized_query, _normalize_name(record.official_name))
        token_score = _score_ratio(token_query, _token_sort_key(record.official_name))
        score = max(name_score, token_score)
        if score < MIN_PLAUSIBLE_SCORE:
            continue
        ranked.append(
            IdentityCandidate(
                official_name=record.official_name,
                username=record.username,
                employee_email=record.employee_email,
                business_title=record.business_title,
                tenure=record.tenure,
                manager_name=record.manager_name,
                score=score,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.official_name.casefold(), item.username))
    return ranked[:MAX_CANDIDATES]


def _build_query_identity(*, shared_first_name: str, shared_last_name: str, shared_name: str) -> tuple[str, str, str]:
    first_name = _normalize_name(shared_first_name)
    last_name = _normalize_name(shared_last_name)
    full_name = _normalize_name(shared_name)
    if not first_name and not last_name and full_name:
        parts = full_name.split()
        first_name = parts[0] if parts else ""
        last_name = parts[-1] if len(parts) > 1 else ""
    elif full_name and (not first_name or not last_name):
        parts = full_name.split()
        first_name = first_name or (parts[0] if parts else "")
        last_name = last_name or (parts[-1] if len(parts) > 1 else "")
    if not full_name:
        full_name = " ".join(part for part in (first_name, last_name) if part)
    return full_name, first_name, last_name


def _normalize_name(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else " " for character in str(value or ""))
    return " ".join(normalized.split())


def _token_sort_key(value: str) -> str:
    normalized = _normalize_name(value)
    return " ".join(sorted(normalized.split())) if normalized else ""


def _score_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if rapidfuzz_fuzz is not None and rapidfuzz_jaro_winkler is not None:
        return float(
            max(
                rapidfuzz_fuzz.WRatio(left, right),
                rapidfuzz_fuzz.ratio(left, right),
                100.0 * rapidfuzz_jaro_winkler.normalized_similarity(left, right),
            )
        )
    return 100.0 * SequenceMatcher(a=left, b=right).ratio()


def _directory_lines(record: DirectoryPersonRecord | None) -> tuple[str, ...]:
    if record is None:
        return ()
    lines: list[str] = []
    if record.business_title:
        lines.append(f"Title: {record.business_title}")
    if record.manager_name:
        lines.append(f"Manager: {record.manager_name}")
    if record.tenure:
        lines.append(f"Tenure: {record.tenure}")
    if record.business_function:
        lines.append(f"Function: {record.business_function}")
    return tuple(lines)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _profile_display_name(
    row: dict[str, Any],
    record: DirectoryPersonRecord | None,
    fallback_person_id: str,
) -> str:
    person_id = str(row.get("person_id") or fallback_person_id or "").strip()
    display_name = str(row.get("display_name") or "").strip()
    if display_name and display_name != person_id:
        return display_name
    official_name = str(row.get("person_official_name") or "").strip()
    if official_name:
        return official_name
    if record is not None and record.official_name:
        return record.official_name
    return person_id or fallback_person_id


def _optional(value: Any) -> str | None:
    rendered = str(value or "").strip()
    return rendered or None


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None and isinstance(metadata.get("metadata"), dict):
        value = metadata["metadata"].get(key)
    return str(value or "").strip()
