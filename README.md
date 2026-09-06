# fashion_trends

Measuring how fast fashion micro-trends rise and fall, using Google Trends
search interest as the signal. For each curated trend it finds the peak, then
quantifies the decline off that peak: how much has dropped, how fast, and how
long it took to lose half its peak — plus a rule-based lifecycle label
(`pre_peak` / `declining` / `collapsed` / `stabilized` / `revived` / `unknown`).

## Scope (current phase)

- **Local-only.** Cloned and run manually. Nothing here is deployed, and
  there is no public web app.
- **Google Trends only**, via `pytrends`. No Instagram/TikTok scraping or any
  other social platform data.
- **No ML or forecasting.** Lifecycle labelling is rule-based against
  measured metrics, not a trained classifier — see
  `fashion_trends.metrics.status`.
- **No social-video references.** The project was sparked by a "viral
  forgotten fashion trends" reel, but no output here cites, reproduces, or
  fact-checks that video's numbers. Every figure is derived independently
  from this repo's own pipeline.

## Setup

Requires Python 3.10+.

```
python -m venv .venv
.venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
python tasks.py install
```

## Quickstart

Three steps, each reading only what the previous one wrote:

```
python tasks.py refresh --offline   # fetch + normalize -> data/processed/*.parquet
python tasks.py charts               # data/processed/*.parquet -> outputs/figures/*.png
python tasks.py app                  # browse the dashboard
```

`refresh_data.py` fetches the curated catalog (`config/trends.yaml`) from
Google Trends, normalizes it across batches, computes every metric, and
writes `data/processed/series.parquet` and `data/processed/metrics.parquet`.
Drop `--offline` to hit the live Google Trends API instead of the committed
`tests/fixtures/` snapshot; both `refresh_data.py` and `build_charts.py`
accept every field on `fashion_trends.settings.Settings` as a flag (e.g.
`--timeframe`, `--geo`) — see that module for the full list.

`build_charts.py` reads the processed parquet files and writes the static
figures (`outputs/figures/decay_curves.png`, `drop_ranking.png`,
`time_to_decline.png`). It makes no network calls.

The Streamlit dashboard reads the same processed parquet files. Its Overview
page carries the three catalog-wide figures (the peak-aligned decay curves,
the drop ranking, and time-to-50%) plus the full sortable table; Trend detail
is a per-trend deep dive; and Live search is the one live path, fetching and
analysing any single ad-hoc keyword on demand without touching the curated
`data/processed/` artifacts. Every figure ships with a plain-language summary
and a "how to read this chart" panel — an axis labelled "weeks since peak"
means nothing on its own, and the copy for all of them lives in one place
(`fashion_trends.app.explainers`) so no two pages describe the same chart
differently.

## Development

`tasks.py` is the one-command entry point for everything below (a plain
Python script rather than a Makefile, since the primary dev machine here is
Windows/PowerShell without `make` on PATH):

```
python tasks.py lint      # ruff check + ruff format --check
python tasks.py test      # pytest
```

Both run cleanly on a clean checkout. Lint and format are configured under
`[tool.ruff]` in `pyproject.toml`; pytest's test paths and markers are under
`[tool.pytest.ini_options]` in the same file — every test runs offline by
default (see `tests/conftest.py`'s network guard).

Optionally, `pip install pre-commit && pre-commit install` runs `lint` and
`test` automatically before each commit (`.pre-commit-config.yaml`).

## Project layout

```
tasks.py                     one-command install/lint/test/refresh/charts/app runner
config/trends.yaml           curated trend catalog (id, keyword, category, notes)
src/fashion_trends/
  settings.py                 every run parameter, in one place
  ingest/                     pytrends client, batching/normalization, cache, fixtures, pipeline
  metrics/                    smoothing, peak detection, decay, lifecycle status, schema
  viz/                        chart theme and figure builders
  app/                        Streamlit page logic, chrome, stylesheet, chart explainers
app/
  streamlit_app.py             dashboard entry point (`streamlit run app/streamlit_app.py`)
  views/                       Overview, Trend detail, Live search pages
.streamlit/config.toml       dashboard colour theme
scripts/
  refresh_data.py               ingestion CLI
  build_charts.py               static-figure CLI
data/
  raw/                         cached raw pulls + provenance manifest
  processed/                   series.parquet, metrics.parquet (dashboard/chart input)
outputs/figures/               generated static charts
docs/
  methodology.md                what each metric means and how it's computed
  trend-selection.md            how the catalog was chosen, and what was rejected
tests/                          unit and offline pipeline tests
```

## Docs

- [`docs/methodology.md`](docs/methodology.md) — what Google Trends' 0-100
  scale actually measures, precise metric definitions, peak detection rules,
  the batching/anchor normalization approach, and stated limitations.
- [`docs/trend-selection.md`](docs/trend-selection.md) — how the catalog in
  `config/trends.yaml` was chosen and what was rejected.
