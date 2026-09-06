"""The dashboard's visual layer: one stylesheet and the small HTML fragments that use it.

Streamlit's defaults are functional but generic, and this dashboard is meant
to be readable by someone who did not build it. Everything cosmetic lives
here so a page module never carries a hex colour or an inline `<style>` of
its own -- the same contract `fashion_trends.viz.theme` holds for matplotlib
figures, applied to the HTML side.

The palette is deliberately shared with the figures rather than picked
independently: `STATUS_COLORS` is imported straight from
`fashion_trends.viz.theme`, so a "collapsed" pill in the table and a
"collapsed" bar in the ranking chart are the same colour by construction and
cannot drift apart. The neutrals (paper, ink, rule) are duplicated in
`.streamlit/config.toml`, which Streamlit reads for its own chrome and which
cannot import Python -- that file says so too.

`inject_styles` is called once per page run, from
`fashion_trends.app.layout.render_header`, so no page has to remember to do
it.
"""

from __future__ import annotations

import streamlit as st

from fashion_trends.viz.theme import STATUS_COLORS

__all__ = [
    "PALETTE",
    "inject_styles",
    "render_kicker",
    "render_metric_card",
    "render_note",
    "status_pill",
    "status_pill_row",
]

# Warm paper neutrals rather than Streamlit's default cool greys: the charts
# are drawn on white cards sitting on this background, and a warm ground
# keeps a page of dense numbers from reading as clinical.
PALETTE = {
    "paper": "#FBFAF8",
    "card": "#FFFFFF",
    "rule": "#E7E1D8",
    "ink": "#1F1C1A",
    "ink_muted": "#6B645C",
    "ink_faint": "#928A80",
    "accent": "#D55E00",
}

# Inter for the interface and Fraunces for the wordmark and titles: a single
# serif accent is most of what separates a dashboard from a spreadsheet. Both
# are fetched from Google Fonts by the browser and fall back through the
# system stack, so the layout is unchanged if that request never lands.
BODY_FONT = '"Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'
DISPLAY_FONT = '"Fraunces", "Iowan Old Style", "Palatino Linotype", Georgia, serif'

_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Fraunces:opsz,wght@9..144,600;9..144,700&"
    "family=Inter:wght@400;500;600;700&display=swap');"
)


def _rgba(hex_color: str, alpha: float) -> str:
    """`hex_color` as an `rgba()` string at `alpha`, for tinted pill backgrounds."""
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _darken(hex_color: str, factor: float = 0.62) -> str:
    """`hex_color` scaled toward black, for pill text legible on that colour's own tint.

    A status colour chosen to read as a solid bar (see
    `fashion_trends.viz.theme.STATUS_COLORS`) is often too light to reuse as
    text on a 14%-tint background of itself -- the greys and the orange
    especially. Darkening the text while leaving the tint alone keeps the
    pill recognisably the same colour as its bar without failing contrast.
    """
    value = hex_color.lstrip("#")
    red, green, blue = (int(int(value[index : index + 2], 16) * factor) for index in (0, 2, 4))
    return f"#{red:02X}{green:02X}{blue:02X}"


_STYLESHEET = f"""
{_FONT_IMPORT}

/* ---- page frame ------------------------------------------------------- */

html, body, .stApp {{
    font-family: {BODY_FONT};
    color: {PALETTE["ink"]};
}}

.stApp {{
    background: {PALETTE["paper"]};
}}

/* Streamlit reserves ~6rem of dead space above the first element; a
   dashboard whose headline sits below the fold is the thing being fixed. */
.block-container {{
    padding-top: 2.4rem;
    padding-bottom: 4rem;
    max-width: 1180px;
}}

[data-testid="stHeader"] {{
    background: transparent;
}}

/* ---- typography ------------------------------------------------------- */

h1, h2, h3 {{
    font-family: {DISPLAY_FONT};
    letter-spacing: -0.01em;
    color: {PALETTE["ink"]};
}}

h1 {{
    font-size: 2.3rem !important;
    font-weight: 700 !important;
    line-height: 1.12 !important;
    padding-top: 0 !important;
}}

h2 {{
    font-size: 1.45rem !important;
    font-weight: 600 !important;
    padding-top: 0.6rem !important;
}}

h3 {{
    font-size: 1.12rem !important;
    font-weight: 600 !important;
}}

p, li {{
    font-size: 0.95rem;
    line-height: 1.62;
}}

/* ---- masthead --------------------------------------------------------- */

/* Centred, unlike everything below it. The page is wide enough that a
   left-set standfirst reads as a narrow column pinned to one edge with a
   third of the row left empty beside it. Centring the whole block — wordmark,
   headline, standfirst, chips — makes that whitespace symmetrical and reads
   as a masthead rather than as text that ran out. The content underneath
   stays left-aligned: a centred hero over left-aligned material is the
   ordinary arrangement, and centring a table or a chart caption would be
   worse than the problem being fixed. */
.ft-masthead {{
    text-align: center;
    border-bottom: 1px solid {PALETTE["rule"]};
    padding-bottom: 1.35rem;
    margin-bottom: 1.6rem;
}}

.ft-wordmark {{
    font-family: {BODY_FONT};
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.19em;
    text-transform: uppercase;
    color: {PALETTE["accent"]};
    margin-bottom: 0.45rem;
}}

.ft-masthead-title {{
    font-family: {DISPLAY_FONT};
    font-size: 2.45rem;
    font-weight: 700;
    line-height: 1.08;
    letter-spacing: -0.02em;
    margin: 0 0 0.5rem 0;
}}

/* `margin: auto` on the sides is what actually centres the paragraph: the
   measure cap keeps it readable, and without the auto margins that capped
   block would still sit hard against the left edge however the text inside
   it is aligned. */
.ft-standfirst {{
    font-size: 1.02rem;
    line-height: 1.6;
    color: {PALETTE["ink_muted"]};
    max-width: 68ch;
    margin: 0 auto 1.15rem auto;
}}

/* ---- provenance chips ------------------------------------------------- */

.ft-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
}}

.ft-masthead .ft-chips {{
    justify-content: center;
}}

.ft-chip {{
    display: inline-flex;
    align-items: baseline;
    gap: 0.4rem;
    background: {PALETTE["card"]};
    border: 1px solid {PALETTE["rule"]};
    border-radius: 999px;
    padding: 0.28rem 0.75rem;
    font-size: 0.78rem;
    line-height: 1.35;
    white-space: nowrap;
}}

.ft-chip-label {{
    color: {PALETTE["ink_faint"]};
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.66rem;
    font-weight: 600;
}}

.ft-chip-value {{
    color: {PALETTE["ink"]};
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}}

/* ---- section headings ------------------------------------------------- */

.ft-kicker {{
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: {PALETTE["ink_faint"]};
    margin: 0.4rem 0 0.35rem 0;
}}

.ft-note {{
    font-size: 0.9rem;
    line-height: 1.6;
    color: {PALETTE["ink_muted"]};
    max-width: 74ch;
    margin: 0 0 0.4rem 0;
}}

/* ---- status pills ----------------------------------------------------- */

.ft-pills {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0.2rem 0 0.6rem 0;
}}

.ft-pill {{
    display: inline-flex;
    align-items: center;
    gap: 0.38rem;
    border-radius: 999px;
    padding: 0.2rem 0.66rem;
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.45;
    white-space: nowrap;
}}

.ft-pill-dot {{
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    flex: 0 0 auto;
}}

.ft-pill-count {{
    font-variant-numeric: tabular-nums;
    opacity: 0.7;
}}

/* ---- metric cards ----------------------------------------------------- */

[data-testid="stMetric"], [data-testid="metric-container"] {{
    background: {PALETTE["card"]};
    border: 1px solid {PALETTE["rule"]};
    border-radius: 12px;
    padding: 0.95rem 1.05rem 0.85rem 1.05rem;
    height: 100%;
}}

[data-testid="stMetricLabel"] p {{
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {PALETTE["ink_faint"]} !important;
}}

[data-testid="stMetricValue"] {{
    font-family: {DISPLAY_FONT};
    font-size: 1.7rem !important;
    font-weight: 600 !important;
    line-height: 1.22 !important;
    color: {PALETTE["ink"]} !important;
    font-variant-numeric: tabular-nums;
}}

/* A hand-built equivalent of the card above, for a tile that needs a note
   line inside its own box -- see `render_metric_card`. */
.ft-metric-card {{
    background: {PALETTE["card"]};
    border: 1px solid {PALETTE["rule"]};
    border-radius: 12px;
    padding: 0.95rem 1.05rem 0.85rem 1.05rem;
    height: 100%;
}}

.ft-metric-card-label {{
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {PALETTE["ink_faint"]};
}}

.ft-metric-card-value {{
    font-family: {DISPLAY_FONT};
    font-size: 1.7rem;
    font-weight: 600;
    line-height: 1.22;
    color: {PALETTE["ink"]};
    font-variant-numeric: tabular-nums;
    margin-top: 0.15rem;
}}

.ft-metric-card-note {{
    font-size: 0.78rem;
    color: {PALETTE["ink_faint"]};
    margin-top: 0.35rem;
}}

/* ---- bordered containers, i.e. the chart cards ------------------------ */

div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {PALETTE["card"]};
    border-color: {PALETTE["rule"]} !important;
    border-radius: 14px;
}}

/* ---- expanders, i.e. the "how to read this chart" panels -------------- */

[data-testid="stExpander"] details {{
    border: 1px solid {PALETTE["rule"]};
    border-radius: 10px;
    background: {PALETTE["paper"]};
}}

[data-testid="stExpander"] summary {{
    font-size: 0.85rem;
    font-weight: 600;
    color: {PALETTE["ink_muted"]};
}}

[data-testid="stExpander"] summary:hover {{
    color: {PALETTE["accent"]};
}}

/* ---- tabs ------------------------------------------------------------- */

.stTabs [data-baseweb="tab-list"] {{
    gap: 1.6rem;
    border-bottom: 1px solid {PALETTE["rule"]};
}}

.stTabs [data-baseweb="tab"] {{
    padding: 0.35rem 0;
    font-size: 0.92rem;
    font-weight: 600;
    color: {PALETTE["ink_faint"]};
}}

.stTabs [aria-selected="true"] {{
    color: {PALETTE["ink"]};
}}

.stTabs [data-baseweb="tab-highlight"] {{
    background-color: {PALETTE["accent"]};
}}

/* ---- table ------------------------------------------------------------ */

[data-testid="stDataFrame"] {{
    border-radius: 10px;
    border: 1px solid {PALETTE["rule"]};
}}

/* ---- sidebar ---------------------------------------------------------- */

[data-testid="stSidebar"] {{
    background: {PALETTE["card"]};
    border-right: 1px solid {PALETTE["rule"]};
}}

/* ---- widgets ---------------------------------------------------------- */

.stButton button, [data-testid="stFormSubmitButton"] button {{
    border-radius: 8px;
    font-weight: 600;
}}

[data-testid="stCaptionContainer"] p {{
    color: {PALETTE["ink_faint"]} !important;
}}
"""


def inject_styles() -> None:
    """Apply the dashboard stylesheet to the current page run.

    Safe to call more than once in a run -- a repeated `<style>` block is
    idempotent -- but in practice `fashion_trends.app.layout.render_header`
    is the only caller, so every page gets it without opting in.
    """
    st.markdown(f"<style>{_STYLESHEET}</style>", unsafe_allow_html=True)


def status_pill(status: str, count: int | None = None) -> str:
    """One lifecycle status as a coloured pill, returned as an HTML string.

    Returns markup rather than rendering it, so a caller can join several
    into a single `st.markdown` call -- Streamlit puts each `st.markdown` in
    its own block element, and one call per pill would stack them vertically
    instead of laying them out in a row.
    """
    color = STATUS_COLORS.get(status, PALETTE["ink_muted"])
    label = status.replace("_", " ")
    count_markup = f'<span class="ft-pill-count">{count}</span>' if count is not None else ""
    return (
        f'<span class="ft-pill" style="background:{_rgba(color, 0.16)};color:{_darken(color)}">'
        f'<span class="ft-pill-dot" style="background:{color}"></span>{label}{count_markup}</span>'
    )


def status_pill_row(counts: dict[str, int]) -> str:
    """A row of status pills with their counts, most common first."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    pills = "".join(status_pill(status, count) for status, count in ordered)
    return f'<div class="ft-pills">{pills}</div>'


def render_kicker(text: str) -> None:
    """Render a small uppercase label above a section, in place of another `st.subheader`.

    Three levels of `st.header`/`st.subheader` on one page flattens into
    noise; a kicker separates sections without competing with the page title.
    """
    st.markdown(f'<div class="ft-kicker">{text}</div>', unsafe_allow_html=True)


def render_metric_card(label: str, value: str, note: str | None = None) -> None:
    """A metric tile with an optional note line inside the same bordered box.

    `st.metric` has no slot for a second line, so a `st.caption` placed after
    one renders as its own element below the card instead of inside it --
    wrong for a tile like "Fastest collapse" whose value means nothing
    without naming which trend it belongs to. This draws the same card by
    hand so that name sits inside the box the number is in.
    """
    note_markup = f'<div class="ft-metric-card-note">{note}</div>' if note else ""
    st.markdown(
        f'<div class="ft-metric-card"><div class="ft-metric-card-label">{label}</div>'
        f'<div class="ft-metric-card-value">{value}</div>{note_markup}</div>',
        unsafe_allow_html=True,
    )


def render_note(text: str) -> None:
    """Render a muted explanatory paragraph, measure-limited for readability.

    `st.caption` is the nearest built-in but sets type too small for a
    sentence a reader is actually meant to read; this is for the one-line
    explanations sitting under a section heading.
    """
    st.markdown(f'<p class="ft-note">{text}</p>', unsafe_allow_html=True)
