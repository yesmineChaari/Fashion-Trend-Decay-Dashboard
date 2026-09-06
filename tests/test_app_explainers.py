import re
from pathlib import Path

import pytest

from fashion_trends.app.explainers import CHART_EXPLAINERS, MAX_READING_LINES, get_explainer

VIEWS_DIR = Path(__file__).resolve().parents[1] / "app" / "views"

# Every `render_explainer("key")` call written in a page module. The point of
# scraping the pages rather than hardcoding a list is that a page rendering a
# chart nobody wrote copy for should fail here, at test time, instead of
# raising in front of whoever opened the dashboard.
_RENDER_CALL = re.compile(r"""render_explainer\(\s*["']([a-z_]+)["']""")


def _keys_used_by_pages():
    keys = set()
    for page in VIEWS_DIR.glob("*.py"):
        keys.update(_RENDER_CALL.findall(page.read_text(encoding="utf-8")))
    return keys


# ---- the registry ----------------------------------------------------


def test_every_chart_rendered_by_a_page_has_an_explainer():
    used = _keys_used_by_pages()

    assert used, f"no render_explainer calls found under {VIEWS_DIR}. The scrape regex has gone stale"
    assert used <= set(CHART_EXPLAINERS)


@pytest.mark.parametrize("key", sorted(CHART_EXPLAINERS))
def test_every_explainer_has_a_summary_and_reading_notes(key):
    explainer = CHART_EXPLAINERS[key]

    assert explainer.summary.strip()
    assert explainer.reading, "an explainer with nothing in `reading` explains no visual element"
    assert all(line.strip() for line in explainer.reading)


@pytest.mark.parametrize("key", sorted(CHART_EXPLAINERS))
def test_no_explainer_outgrows_the_reading_budget(key):
    # Wording rule from the module docstring: a fourth bullet means the chart
    # is doing too much, not that the explanation needs to be longer.
    assert len(CHART_EXPLAINERS[key].reading) <= MAX_READING_LINES


@pytest.mark.parametrize("key", sorted(CHART_EXPLAINERS))
def test_no_explainer_leaks_a_module_path_into_reader_facing_copy(key):
    # Wording rule from the module docstring: this copy describes what the
    # reader is looking at. `fashion_trends.metrics.decay.compute_time_to_half`
    # belongs in the methodology doc, not under a chart.
    explainer = CHART_EXPLAINERS[key]
    prose = " ".join([explainer.summary, *explainer.reading])

    assert "fashion_trends." not in prose


# ---- get_explainer ----------------------------------------------------


def test_get_explainer_returns_the_registered_entry():
    assert get_explainer("drop_ranking") is CHART_EXPLAINERS["drop_ranking"]


def test_get_explainer_names_the_registered_keys_when_one_is_missing():
    with pytest.raises(KeyError) as error:
        get_explainer("not_a_chart")

    assert "drop_ranking" in str(error.value)
