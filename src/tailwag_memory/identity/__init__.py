"""Directory-backed identity services."""

from .service import (
    DirectoryIdentityService,
    employee_email_from_username,
    load_directory_records_from_snowflake,
)

__all__ = [
    "DirectoryIdentityService",
    "employee_email_from_username",
    "load_directory_records_from_snowflake",
]
