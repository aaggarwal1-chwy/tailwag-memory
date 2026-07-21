"""Snowflake connection and employee-directory row loading."""

from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Callable

from ..models import DirectoryPersonRecord


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


def load_env_file(path: Path = Path(".snowflake_env")) -> None:
    candidates = [Path.cwd() / ".snowflake_env", path, Path(".env")]
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
                str(
                    description[0]
                    if isinstance(description, (tuple, list))
                    else getattr(description, "name", "")
                ).upper()
                for description in (getattr(cursor, "description", None) or ())
            ]
        return [
            record_from_row(
                row,
                site_code=str(site_code or "").strip(),
                email_domain=email_domain,
                columns=columns,
            )
            for row in rows
        ]
    finally:
        connection.close()


def record_from_row(
    row: Any,
    *,
    site_code: str,
    email_domain: str,
    columns: list[str] | None = None,
) -> DirectoryPersonRecord:
    values_by_column = row_values_by_column(row, columns or list(EMPLOYEE_COLUMNS))

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


def row_values_by_column(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return {str(key).upper(): value for key, value in row.items()}
    values = tuple(row)
    return {
        str(column or "").upper(): values[index]
        for index, column in enumerate(columns)
        if index < len(values)
    }
