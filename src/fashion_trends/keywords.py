"""Loader for the curated trend catalog (config/trends.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_CATEGORIES = {"aesthetic", "garment", "accessory", "styling"}
REQUIRED_FIELDS = ("id", "keyword", "display_name", "category", "notes")

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "trends.yaml"


class TrendCatalogError(ValueError):
    """Raised when the trend catalog file fails to parse or validate."""


@dataclass(frozen=True)
class Trend:
    id: str
    keyword: str
    display_name: str
    category: str
    notes: str


def load_trends(path: Path | str = DEFAULT_CATALOG_PATH) -> list[Trend]:
    """Parse and validate the trend catalog, returning typed `Trend` objects.

    Raises `TrendCatalogError` on a malformed entry, an unknown category,
    or a duplicate `id`/`keyword` across entries.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(raw, list) or not raw:
        raise TrendCatalogError(f"{path} must contain a non-empty list of trend entries")

    seen_ids: set[str] = set()
    seen_keywords: set[str] = set()
    trends: list[Trend] = []

    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise TrendCatalogError(f"{path}: entry #{index} is not a mapping: {entry!r}")

        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            label = entry.get("id", f"#{index}")
            raise TrendCatalogError(
                f"{path}: entry '{label}' is missing required field(s): {', '.join(missing)}"
            )

        trend_id = entry["id"]
        keyword = entry["keyword"]
        category = entry["category"]

        if category not in VALID_CATEGORIES:
            raise TrendCatalogError(
                f"{path}: entry '{trend_id}' has invalid category '{category}' "
                f"(must be one of {sorted(VALID_CATEGORIES)})"
            )

        if trend_id in seen_ids:
            raise TrendCatalogError(f"{path}: duplicate id '{trend_id}'")
        if keyword in seen_keywords:
            raise TrendCatalogError(f"{path}: duplicate keyword '{keyword}'")

        seen_ids.add(trend_id)
        seen_keywords.add(keyword)

        trends.append(
            Trend(
                id=trend_id,
                keyword=keyword,
                display_name=entry["display_name"],
                category=category,
                notes=entry["notes"],
            )
        )

    return trends
