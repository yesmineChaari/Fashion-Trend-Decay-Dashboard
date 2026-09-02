import pytest

from fashion_trends.keywords import Trend, TrendCatalogError, load_trends

VALID_YAML = """
- id: mob_wife
  keyword: "mob wife aesthetic"
  display_name: "Mob wife aesthetic"
  category: aesthetic
  notes: "example"
- id: cargo_pants
  keyword: "cargo pants trend"
  display_name: "Cargo pants"
  category: garment
  notes: "example"
"""


def test_load_trends_default_catalog():
    trends = load_trends()

    assert 20 <= len(trends) <= 30
    assert all(isinstance(t, Trend) for t in trends)
    assert len({t.id for t in trends}) == len(trends)
    assert len({t.keyword for t in trends}) == len(trends)
    assert {t.category for t in trends} <= {"aesthetic", "garment", "accessory", "styling"}
    assert all(t.notes for t in trends)


def test_load_trends_parses_valid_catalog(tmp_path):
    catalog = tmp_path / "trends.yaml"
    catalog.write_text(VALID_YAML, encoding="utf-8")

    trends = load_trends(catalog)

    assert trends == [
        Trend(
            id="mob_wife",
            keyword="mob wife aesthetic",
            display_name="Mob wife aesthetic",
            category="aesthetic",
            notes="example",
        ),
        Trend(
            id="cargo_pants",
            keyword="cargo pants trend",
            display_name="Cargo pants",
            category="garment",
            notes="example",
        ),
    ]


def test_load_trends_rejects_duplicate_id(tmp_path):
    catalog = tmp_path / "trends.yaml"
    catalog.write_text(
        """
- id: dup
  keyword: "keyword one"
  display_name: "One"
  category: aesthetic
  notes: "example"
- id: dup
  keyword: "keyword two"
  display_name: "Two"
  category: garment
  notes: "example"
""",
        encoding="utf-8",
    )

    with pytest.raises(TrendCatalogError, match="duplicate id"):
        load_trends(catalog)


def test_load_trends_rejects_duplicate_keyword(tmp_path):
    catalog = tmp_path / "trends.yaml"
    catalog.write_text(
        """
- id: one
  keyword: "same keyword"
  display_name: "One"
  category: aesthetic
  notes: "example"
- id: two
  keyword: "same keyword"
  display_name: "Two"
  category: garment
  notes: "example"
""",
        encoding="utf-8",
    )

    with pytest.raises(TrendCatalogError, match="duplicate keyword"):
        load_trends(catalog)


def test_load_trends_rejects_missing_field(tmp_path):
    catalog = tmp_path / "trends.yaml"
    catalog.write_text(
        """
- id: incomplete
  keyword: "some keyword"
  category: aesthetic
  notes: "example"
""",
        encoding="utf-8",
    )

    with pytest.raises(TrendCatalogError, match="missing required field"):
        load_trends(catalog)


def test_load_trends_rejects_invalid_category(tmp_path):
    catalog = tmp_path / "trends.yaml"
    catalog.write_text(
        """
- id: bad_category
  keyword: "some keyword"
  display_name: "Bad"
  category: not_a_real_category
  notes: "example"
""",
        encoding="utf-8",
    )

    with pytest.raises(TrendCatalogError, match="invalid category"):
        load_trends(catalog)


def test_load_trends_rejects_empty_catalog(tmp_path):
    catalog = tmp_path / "trends.yaml"
    catalog.write_text("[]", encoding="utf-8")

    with pytest.raises(TrendCatalogError, match="non-empty"):
        load_trends(catalog)
