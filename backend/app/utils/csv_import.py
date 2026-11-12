"""
CSV Roll Import - Phase 3 (remediated)
Vote Without Doubt - Backend

Validation is deliberately strict about *shape* and permissive about *format*:

* Shape is enforced: encoding, header presence, the three required columns,
  ragged rows, empty required values, and per-row data types.
* The voter-id convention is a student number: 3-50 ASCII letters and digits
  containing at least one digit. This rejects quoting, whitespace and SQL
  metacharacters such as ``' OR 1=1--`` without inventing a college-specific
  layout the project has never specified.

The parser returns ``(rows, errors)``. Callers decide whether to abort; nothing
is written to the database by this module.
"""

import csv
import io
import re
from typing import Any, Dict, List, Tuple

#: Hard ceiling so a hostile upload cannot exhaust memory.
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000

#: Logical fields that must resolve from the header, using the same keys as
#: COLUMN_ALIASES.
REQUIRED_COLUMNS = ('usn', 'name', 'email')

#: Student-number convention: ASCII alphanumeric, 3-50 chars, at least one digit.
USN_PATTERN = re.compile(r'^[A-Za-z0-9]{3,50}$')

#: Pragmatic e-mail shape check: one @, a dotted domain, no whitespace/controls.
EMAIL_PATTERN = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')

#: Plausible range for a year of study.
MIN_YEAR = 1
MAX_YEAR = 6

#: Header aliases accepted for each logical field.
COLUMN_ALIASES = {
    'usn': ('usn', 'student id', 'studentid', 'student number', 'roll no', 'id'),
    'name': ('name', 'full name', 'fullname', 'student name'),
    'email': ('college email', 'collegeemail', 'college_email', 'email', 'mail'),
    'department': ('department', 'dept'),
    'year': ('year', 'year of study', 'year_of_study', 'yearofstudy'),
}


class RollImportError(Exception):
    """Raised when a CSV cannot be parsed at all (wrong encoding, no header)."""


def _has_control_chars(value: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)


def validate_usn(value: str) -> bool:
    """True when the value matches the student-number convention."""
    return bool(value) and bool(USN_PATTERN.match(value)) and any(c.isdigit() for c in value)


def validate_email(value: str) -> bool:
    return bool(value) and bool(EMAIL_PATTERN.match(value))


def _build_mapping(fieldnames: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for original in fieldnames:
        key = (original or '').strip().lower()
        for logical, aliases in COLUMN_ALIASES.items():
            if logical in mapping:
                continue
            if key in aliases:
                mapping[logical] = original
                break
    return mapping


def validate_and_parse_roll(csv_content: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parse and validate an electoral-roll CSV.

    Returns ``(rows, errors)``. ``rows`` contains only well-formed records;
    every rejected record contributes one human-readable entry to ``errors``.
    """
    if not isinstance(csv_content, (bytes, bytearray)):
        raise RollImportError('Invalid file encoding')
    if len(csv_content) > MAX_CSV_BYTES:
        raise RollImportError('CSV exceeds the maximum allowed size')
    if not csv_content.strip():
        raise RollImportError('Empty or invalid CSV')

    try:
        text = csv_content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise RollImportError('Invalid file encoding')

    reader = csv.DictReader(io.StringIO(text, newline=''))
    if not reader.fieldnames:
        raise RollImportError('Empty or invalid CSV')

    mapping = _build_mapping(reader.fieldnames)
    missing = [name for name in REQUIRED_COLUMNS if name not in mapping]
    if missing:
        raise RollImportError('Missing required columns: USN, Name, College Email')

    errors: List[str] = []
    rows: List[Dict[str, Any]] = []
    seen_usn: Dict[str, int] = {}

    for line_no, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            errors.append('Row limit reached; remaining rows ignored')
            break

        # A short row leaves None for absent trailing cells.
        if raw is None or all(value is None for value in raw.values()):
            errors.append(f'Line {line_no}: empty row')
            continue

        values = {key: (value.strip() if isinstance(value, str) else '')
                  for key, value in raw.items() if key is not None}

        usn = values.get(mapping['usn'], '')
        name = values.get(mapping['name'], '')
        email = values.get(mapping['email'], '').lower()

        if not usn:
            errors.append(f'Line {line_no}: Missing USN')
            continue
        if not validate_usn(usn):
            # Deliberately does not echo the rejected value back to the caller.
            errors.append(f'Line {line_no}: Invalid USN format')
            continue
        if usn in seen_usn:
            errors.append(f'Line {line_no}: Duplicate USN (first seen line {seen_usn[usn]})')
            continue
        if not name:
            errors.append(f'Line {line_no}: Missing Name')
            continue
        if _has_control_chars(name):
            errors.append(f'Line {line_no}: Invalid characters in Name')
            continue
        if len(name) > 200:
            errors.append(f'Line {line_no}: Name too long')
            continue
        if not email:
            errors.append(f'Line {line_no}: Missing College Email')
            continue
        if _has_control_chars(email) or not validate_email(email):
            errors.append(f'Line {line_no}: Invalid email format')
            continue

        record: Dict[str, Any] = {'usn': usn, 'name': name, 'email': email}

        if 'department' in mapping:
            department = values.get(mapping['department'], '')
            if department and len(department) <= 100 and not _has_control_chars(department):
                record['department'] = department
        if 'year' in mapping:
            raw_year = values.get(mapping['year'], '')
            if raw_year:
                try:
                    year = int(raw_year)
                except ValueError:
                    errors.append(f'Line {line_no}: Year of study is not a number')
                    continue
                if not (MIN_YEAR <= year <= MAX_YEAR):
                    errors.append(f'Line {line_no}: Year of study out of range 1-6')
                    continue
                record['year'] = year

        seen_usn[usn] = line_no
        rows.append(record)

    return rows, errors
