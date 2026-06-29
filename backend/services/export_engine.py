"""Safe report export, in-memory report metadata, and preview serialization."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import OUTPUTS_DIR, PREVIEW_ROW_LIMIT
from ..utils.file_utils import sanitize_filename


def create_report_id(kind: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{sanitize_filename(kind)}_{timestamp}_{uuid.uuid4().hex[:8]}"


def dataframe_preview(df: pd.DataFrame, limit: int = PREVIEW_ROW_LIMIT) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return json.loads(df.head(limit).to_json(orient="records", date_format="iso"))


def export_dataframe(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def export_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")


@dataclass(slots=True)
class ReportMetadata:
    report_id: str
    session_id: str
    kind: str
    created_at: datetime
    folder: Path
    clean_filename: str
    files: dict[str, str]
    summary: dict[str, Any]


class ReportRegistry:
    def __init__(self) -> None:
        self._reports: dict[str, ReportMetadata] = {}
        self._lock = threading.RLock()

    def register(self, metadata: ReportMetadata) -> None:
        with self._lock:
            self._reports[metadata.report_id] = metadata

    def get(self, report_id: str, session_id: str) -> ReportMetadata:
        with self._lock:
            metadata = self._reports.get(report_id)
        if metadata is None or metadata.session_id != session_id:
            raise KeyError("Report not found for this session")
        return metadata

    def update_file(self, report_id: str, key: str, filename: str) -> None:
        with self._lock:
            self._reports[report_id].files[key] = filename

    def recent(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            matches = [item for item in self._reports.values() if item.session_id == session_id]
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return [
            {
                "report_id": item.report_id,
                "kind": item.kind,
                "created_at": item.created_at.isoformat(),
                "net_pnl": item.summary.get("net_pnl"),
                "transactions": item.summary.get("total_transactions"),
            }
            for item in matches[:limit]
        ]


REPORTS = ReportRegistry()


def report_folder(report_id: str) -> Path:
    folder = OUTPUTS_DIR / report_id
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def download_url(report_id: str, filename: str) -> str:
    return f"/api/download/{report_id}/{filename}"

