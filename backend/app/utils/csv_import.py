"""
CSV Roll Import - Phase 3
"""

import csv
import io
from typing import List, Dict, Any, Tuple


class RollImportError(Exception):
    pass


def validate_and_parse_roll(csv_content: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse and validate electoral roll CSV
    Expected columns: USN, Name, College Email (case-insensitive)
    """
    errors = []
    rows = []
    
    try:
        # Try to decode
        text = csv_content.decode('utf-8-sig')
    except Exception:
        raise RollImportError("Invalid file encoding")
    
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RollImportError("Empty or invalid CSV")
    
    # Normalize fieldnames
    fieldnames = [f.strip().lower() for f in reader.fieldnames]
    required = ['usn', 'name', 'college email']
    for r in required:
        if r not in fieldnames and r not in ' '.join(fieldnames):  # simple check
            # try flexible mapping
            pass
    
    # Flexible mapping
    mapping = {}
    for fn in reader.fieldnames:
        f = fn.strip().lower()
        if f in ('usn', 'student id', 'studentid', 'id'):
            mapping['usn'] = fn
        elif f in ('name', 'full name', 'student name'):
            mapping['name'] = fn
        elif f in ('college email', 'email', 'college_email', 'mail'):
            mapping['email'] = fn
        elif f in ('department', 'dept'):
            mapping['department'] = fn
        elif f in ('year', 'year of study', 'year_of_study'):
            mapping['year'] = fn
    
    if 'usn' not in mapping or 'name' not in mapping or 'email' not in mapping:
        raise RollImportError("Missing required columns: USN, Name, College Email")
    
    for i, row in enumerate(reader, 2):  # 2-based line number
        try:
            usn = str(row.get(mapping['usn'], '')).strip()
            name = str(row.get(mapping['name'], '')).strip()
            email = str(row.get(mapping['email'], '')).strip()
            if not usn:
                errors.append(f"Line {i}: Missing USN")
                continue
            if not name:
                errors.append(f"Line {i}: Missing Name")
                continue
            if not email:
                errors.append(f"Line {i}: Missing College Email")
                continue
            # Basic email check
            if '@' not in email:
                errors.append(f"Line {i}: Invalid email format")
                continue
            rec = {
                'usn': usn,
                'name': name,
                'email': email.lower()
            }
            if 'department' in mapping:
                rec['department'] = str(row.get(mapping['department'], '')).strip() or None
            if 'year' in mapping:
                y = str(row.get(mapping['year'], '')).strip()
                try:
                    rec['year'] = int(y) if y else None
                except ValueError:
                    rec['year'] = None
            rows.append(rec)
        except Exception as e:
            errors.append(f"Line {i}: Invalid data")
    
    # Check duplicates in CSV
    seen = set()
    for r in rows:
        if r['usn'] in seen:
            errors.append(f"Duplicate USN in CSV: {r['usn']}")
        seen.add(r['usn'])
    
    return rows, errors
