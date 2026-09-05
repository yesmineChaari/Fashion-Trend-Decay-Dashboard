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
pip install -r requirements.txt
pip install -e .
```

## Quickstart

Three steps, each reading only what the previous one wrote:

```
python scripts/refresh_data.py --offline   # fetch + normalize -> data/processed/*.parquet
python scripts/build_charts.py             # data/processed/*.parquet -> outputs/figures/*.png
streamlit run app/streamlit_app.py         # browse the dashboard
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

The Streamlit dashboard reads the same processed parquet files and adds one
live path: its Live search page fetches and analyses any single ad-hoc
keyword on demand, without touching the curated `data/processed/` artifacts.

## Project layout

```
config/trends.yaml           curated trend catalog (id, keyword, category, notes)
src/fashion_trends/
  settings.py                 every run parameter, in one place
  ingest/                     pytrends client, batching/normalization, cache, fixtures, pipeline
  metrics/                    smoothing, peak detection, decay, lifecycle status, schema
  viz/                        chart theme and figure builders
  app/                        Streamlit page logic and cached data-access layer
app/
  streamlit_app.py             dashboard entry point (`streamlit run app/streamlit_app.py`)
  views/                       Overview, Trend detail, Live search pages
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
