"""Shared append-only audit trail writer."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "ECLIPSE"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG = RUNTIME_DIR / "audit.log"


def runtime_path(name: str) -> Path:
    return RUNTIME_DIR / name


def write_event(module: str, event: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] [{module}] {event}\n")
