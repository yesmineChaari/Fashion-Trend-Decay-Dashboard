from fashion_trends.app.styles import _darken, _rgba, status_pill, status_pill_row
from fashion_trends.metrics.status import STATUS_COLLAPSED, STATUS_DECLINING
from fashion_trends.viz.theme import STATUS_COLORS

# ---- colour helpers ----------------------------------------------------


def test_rgba_converts_a_hex_colour_to_an_rgba_string():
    assert _rgba("#D55E00", 0.16) == "rgba(213, 94, 0, 0.16)"


def test_darken_returns_a_hex_colour_no_lighter_than_the_original():
    darkened = _darken("#E69F00")

    assert darkened.startswith("#")
    assert len(darkened) == 7
    assert int(darkened[1:3], 16) < 0xE6


def test_darken_handles_a_grey_without_shifting_its_hue():
    # `pre_peak` and `unknown` are greys; darkening must keep the channels
    # equal or the pill picks up a colour cast the chart's bar doesn't have.
    red, green, blue = (int(_darken("#CCCCCC")[index : index + 2], 16) for index in (1, 3, 5))

    assert red == green == blue


# ---- pills ----------------------------------------------------------


def test_status_pill_uses_the_same_colour_as_the_charts():
    # The pill and the ranking chart's bar must agree by construction --
    # see the module docstring for why the palette is imported, not copied.
    markup = status_pill(STATUS_COLLAPSED)

    assert STATUS_COLORS[STATUS_COLLAPSED] in markup


def test_status_pill_renders_the_label_without_its_underscores():
    assert "pre peak" in status_pill("pre_peak")


def test_status_pill_omits_the_count_when_none_is_given():
    assert "ft-pill-count" not in status_pill(STATUS_COLLAPSED)
    assert "ft-pill-count" in status_pill(STATUS_COLLAPSED, 4)


def test_status_pill_falls_back_for_an_unknown_status():
    # A status outside STATUS_COLORS should still render a drawable pill,
    # matching `fashion_trends.viz.theme.status_style`'s fallback behaviour.
    assert "ft-pill" in status_pill("not_a_real_status")


def test_status_pill_row_orders_by_count_descending():
    markup = status_pill_row({STATUS_DECLINING: 2, STATUS_COLLAPSED: 9})

    assert markup.index(STATUS_COLLAPSED) < markup.index(STATUS_DECLINING)
