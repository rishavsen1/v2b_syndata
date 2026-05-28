"""CalibrationSource protocol — one implementation per real-world dataset."""
from __future__ import annotations

from typing import Any, Protocol

from ..feature_extractor import SessionFeatures


class CalibrationSource(Protocol):
    """Per-source fetch + normalize. Orchestrator stays source-agnostic."""

    per_user_csv_filename: str

    def fetch_sessions(self, config: dict[str, Any]) -> list[SessionFeatures]: ...

    def dataset_name(self) -> str: ...

    def provenance_prefix(self, config: dict[str, Any]) -> str: ...

    def extra_metadata(self, config: dict[str, Any]) -> dict[str, Any]: ...

    def token_help_message(self) -> str: ...

    def parse_args(self, raw: list[str]) -> dict[str, Any]: ...
