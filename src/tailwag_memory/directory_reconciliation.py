from __future__ import annotations


def person_directory_reconciliation_cypher(person_variable: str = "p") -> str:
    """Return Cypher that links a Person to directory rows by email username."""
    return f"""
                WITH *
                CALL ({person_variable}) {{
                  WITH {person_variable},
                       CASE
                         WHEN {person_variable}.email IS NULL OR NOT {person_variable}.email CONTAINS '@' THEN ''
                         ELSE toLower(split({person_variable}.email, '@')[0])
                       END AS directory_username
                  OPTIONAL MATCH (directory_record:EmployeeDirectoryRecord {{username: directory_username}})
                  WITH {person_variable}, [
                    record IN collect(directory_record)
                    WHERE record IS NOT NULL
                  ] AS directory_records
                  FOREACH (directory_record IN directory_records |
                    MERGE ({person_variable})-[:HAS_DIRECTORY_RECORD]->(directory_record)
                  )
                  RETURN size(directory_records) AS directory_record_reconciliation_count
                }}
                """
