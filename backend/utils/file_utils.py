"""Path and filename safety helpers."""

from __future__ import annotations

import re
from pathlib import Path


SAFE_REPORT_ID = re.compile(r"^[A-Za-z0-9_-]{10,100}$")


def sanitize_filename(value: str, fallback: str = "report") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip()).strip("._")
    return (cleaned or fallback)[:160]


def resolve_safe_report_file(root: Path, report_id: str, filename: str) -> Path:
    if not SAFE_REPORT_ID.fullmatch(report_id):
        raise ValueError("Invalid report id")
    if filename != Path(filename).name or filename in {"", ".", ".."}:
        raise ValueError("Invalid filename")
    safe_name = sanitize_filename(filename, fallback="")
    if safe_name != filename:
        raise ValueError("Invalid filename")
    root_resolved = root.resolve()
    candidate = (root_resolved / report_id / filename).resolve()
    if root_resolved not in candidate.parents:
        raise ValueError("Invalid download path")
    return candidate

