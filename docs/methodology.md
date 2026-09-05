# Methodology

How each metric in `metrics.parquet` is defined, so a reader comparing this
project's figures against any other source knows exactly what they mean.

## The `metrics.parquet` schema

One row per trend. `fashion_trends.metrics.compute_all` is the single entry
point that produces it — the pipeline and any future live-lookup (the
dashboard's live search) both call it, so there is exactly one place these
numbers are computed. `fashion_trends.metrics.schema.validate_metrics_schema`
checks every column and dtype below against what actually came back before a
frame is written or returned, so a run fails loudly rather than silently
persisting a table the dashboard or charts can't read correctly.

Nullable types are used throughout on purpose: a null metric is a meaningful
state (no peak yet, a fit too short to trust, a trend that never crossed half
its peak), never coerced to `0` — a `pct_dropped` of `0` and an unknown
`pct_dropped` mean opposite things.

| Column | Type | Meaning |
| --- | --- | --- |
| `trend_id` | string | Catalog id (`config/trends.yaml`). |
| `keyword` | string | The literal Google Trends search term. |
| `display_name` | string | Human-readable label for charts/dashboard. |
| `category` | string | One of `config/trends.yaml`'s `VALID_CATEGORIES`. |
| `isolate` | bool | Whether the trend was pulled alone with the anchor (see `fashion_trends.settings.Settings.anchor_keyword`). |
| `low_resolution` | bool | Rescaled peak below `low_resolution_threshold` — shape not trustworthy for decay metrics. |
| `peak_date` | datetime | Date of the smoothed-series peak. |
| `peak_value` | float | Smoothed interest (0-100 scale) at the peak. |
| `peak_value_raw` | float | Unsmoothed interest at the peak week. |
| `weeks_since_peak` | int | Weeks from peak to the end of the pulled window. |
| `peak_is_spike` | bool | Peak's height rests on a single week, not a hump. |
| `has_secondary_peak` | bool | A second hump reaching `secondary_peak_ratio` of the peak was found. |
| `secondary_peak_date` | datetime | Date of that secondary hump, if any. |
| `secondary_peak_value` | float | Smoothed interest at the secondary hump, if any. |
| `peak_at_boundary` | bool | Peak sits within `peak_boundary_weeks` of either end of the window — the real peak may be outside it. |
| `pre_peak` | bool | Peak is the most recent week and still climbing. |
| `pct_dropped` | float | % dropped from peak, clamped to `[0, 100]`. |
| `current_value` | float | Trailing mean of raw interest behind `pct_dropped`. |
| `current_window_end` | datetime | Last week folded into `current_value`. |
| `current_above_peak` | bool | Current level reads above peak — the peak was misdetected. |
| `decay_rate_linear` | float | Percentage points of peak lost per week. |
| `decay_rate_exp` | float | Weekly exponential decay constant `k`. |
| `decay_fit_r2` | float | Fraction of variance the exponential fit explains. |
| `decay_fit_weeks` | int | Weeks of post-peak data behind the fit. |
| `weeks_to_half` | int | Weeks from peak until a sustained drop below half of it. |
| `half_life_date` | datetime | Date of that sustained crossing. |
| `time_to_half_status` | string | `crossed` / `still_above_half` / `pre_peak` / `unknown` — see below. |
| `status` | string | `pre_peak` / `declining` / `collapsed` / `stabilized` / `revived` / `unknown` — see below. |
| `data_pull_date` | datetime | When the interest data behind this row was current. |
| `timeframe` | string | The Google Trends `timeframe` the pull used (e.g. `today 5-y`). |
| `geo` | string | The Google Trends `geo` the pull used (e.g. `US`). |

## % dropped since peak (`pct_dropped`)

```
pct_dropped = (peak_value - current_value) / peak_value * 100
```

`peak_value` is the smoothed peak found by
`fashion_trends.metrics.peaks.detect_peak` (see that module for how it
qualifies a peak against false spikes, revivals, and window-edge cases).

`current_value` is **the mean of the last `smoothing_window` complete
weeks** of raw interest — not the single most recent week. A trend's most
recent week is noisy enough on its own to swing the headline drop by double
digits; averaging it with the `smoothing_window` weeks before it (the same
window width used to smooth the series for peak detection) absorbs that
noise while still describing where the trend stands now rather than months
ago. Gap weeks inside that window are skipped, not counted as zero. The
trailing partial week (the current, still-accumulating week of a live pull)
is always excluded: `fashion_trends.ingest.pytrends_client` drops every row
Google Trends flags `isPartial` as the response comes in, and
`fashion_trends.metrics.smoothing.preprocess_series` will drop them too if
handed an unprocessed pull directly. That week reads low purely for having
been half-observed, and it lands inside the very window averaged here — so
keeping it would inflate every "% dropped" figure in a run rather than
producing an obviously wrong number.

`current_value` and the date of the last week folded into it
(`current_window_end`) are recorded alongside `pct_dropped` so the number is
auditable — a reader can see exactly what window produced it.

**Rules:**

* Clamped to `[0, 100]`. A current level *above* the peak means the peak was
  misdetected, not that the trend is rising again — that case is surfaced as
  `current_above_peak = true` rather than as a negative percentage.
* `None` (not `0`) when the trend is `pre_peak` — still climbing into its
  most recent week, with no decay to measure yet.
* `None` when the peak itself is `0`: no measurable interest was ever
  recorded, so there is no drop to express as a fraction of it.

See `fashion_trends.metrics.decay` for the implementation.

## Decay rate (`decay_rate_linear`, `decay_rate_exp`)

Two trends can share the same `pct_dropped` and have nothing else in
common: one collapsed in eight weeks, the other faded gently over two
years. The decay rate is what separates them.

### Linear reading

```
decay_rate_linear = pct_dropped / weeks_since_peak
```

Percentage points of the peak lost per week, directly comparable to
`pct_dropped` and the number to quote when a reader asks how fast a trend
fell. It assumes the decline was a straight line, which is why it is not
reported alone.

### Exponential fit

Real decay curves are closer to exponential than linear — steep at first,
then flattening — so `log(interest_smooth)` is also fitted by least squares
against weeks since peak, over the post-peak segment (the peak week to the
end of the pulled window):

```
interest ≈ peak * exp(-decay_rate_exp * weeks_since_peak)
```

`decay_rate_exp` is the weekly decay constant `k`. A `k` of 0.05 means the
trend loses about 4.9% (`1 - exp(-0.05)`) of *whatever interest is left*
each week, not 5% of its original peak.

`decay_fit_r2` is the fraction of the variance in `log(interest)` that
constant explains, and it is as important as the constant itself: a trend
that fell off a cliff and then plateaued fits an exponential badly, and a
reader deciding whether to trust one decay number for that trend should be
able to see so. `decay_fit_weeks` records how many weeks went into the fit.

The fit runs on the smoothed series. A centred rolling mean scales an
exponential by a constant factor rather than bending it, so it leaves the
fitted constant alone while keeping one noisy week from tilting it.

**Rules:**

* `None` for both variants when the trend is `pre_peak` — no decay to
  measure yet.
* `decay_rate_linear` is `None` when `pct_dropped` is (no peak, or a zero
  peak), and when `weeks_since_peak` is `0`: the peak is the most recent
  week, so no time has passed for the drop to spread over.
* The fit fields are `None` when fewer than `min_decay_fit_weeks` (default
  8) weeks of the post-peak segment can be fitted. Too short a segment
  yields a constant that extrapolates wildly, and a null is the more honest
  answer.
* Weeks that are gaps, or that sit at zero, cannot be logged and are dropped
  from the fit rather than floored to a small constant — which would invent
  a slope out of the choice of floor. Because the series sits on a complete
  weekly index, dropping a week does not shift the weeks after it.

See `fashion_trends.metrics.decay` for the implementation.

## Lifecycle status (`status`)

A plain-language label for where a trend sits in its life, so the dashboard
can group and filter meaningfully. This is descriptive labelling of already-
computed metrics — no ML, no training, no forecast of what a trend will do
next.

* `pre_peak` — the peak is the most recent week and the series is still
  climbing into it. No decline to measure yet.
* `declining` — clearly post-peak and still falling over the recent window.
* `collapsed` — dropped at least `collapsed_pct_dropped_threshold` (default
  70%) from peak.
* `stabilized` — post-peak but flat over the trailing
  `stabilized_window_weeks` (default 26) weeks, having retained at least
  `stabilized_min_retained_pct` (default 40%) of peak. The distinction this
  project cares most about: a trend that became a wardrobe staple, not one
  that quietly vanished.
* `revived` — a secondary peak was flagged during peak detection (see
  `has_secondary_peak` above).
* `unknown` — no peak could be found at all (an empty or all-gap series).
  Not one of the five lifecycle stages; the same "no data" escape hatch used
  elsewhere in this table (compare `time_to_half_status`'s `unknown`).

**Rule order** (first match wins, since a trend can satisfy more than one of
these at once): `unknown` → `pre_peak` → `revived` → `collapsed` →
`stabilized` → `declining` (the default for any post-peak trend matching
none of the above). `revived` is checked ahead of `collapsed`/`stabilized`
because a trend coming back is the more informative story even when its
current level also happens to be deep in a drop or sitting flat;
`collapsed` is checked ahead of `stabilized` so a trend that faded to a
residual floor and then went flat there is reported as collapsed, not as a
plateau worth calling stability.

"Flat" is the trailing window's range as a fraction of its own mean, within
`stabilized_flat_tolerance` (default 0.15) — a fixed absolute range would
call a small residual trend "volatile" for movements that are proportionally
tiny. The window must be full of actual observations (no gap weeks) and the
trend must be at least `stabilized_window_weeks` past its peak, so a trend
that only just peaked can't read its own peak plateau as stability.

See `fashion_trends.metrics.status` for the implementation.

## Time to 50% decline (`weeks_to_half`)

The normalized "how fast do trends die" figure — comparable across trends
regardless of how popular any of them ever was, because each is measured
against its own peak.

```
weeks_to_half = first_week_after_peak_where(interest_smooth < 0.5 * peak_value) - peak_week
```

`half_life_date` records the date of that week for the detail view.

The crossing is read off the **smoothed** series, and it only counts once
the series *stays* below the threshold for `half_life_sustained_weeks`
(default 2) consecutive weeks. Those two rules are halves of the same
defence: a single noisy week that ducks under half the peak and recovers
the week after is not the week a trend halved, and treating it as one would
report a trend as dead months before it was. A gap week breaks a run rather
than counting as still-below — a hole in the data is not evidence the trend
stayed down through it.

### The three ways this metric is null

`weeks_to_half` is `None` in three unrelated situations, so
`time_to_half_status` names which one applies:

* `crossed` — a genuine crossing was found; `weeks_to_half` is set.
* `still_above_half` — the trend has never dropped below half its peak.
  **This is a result, not missing data**: a trend with staying power. It
  must be presented as such rather than hidden as a row that failed to
  compute.
* `pre_peak` — the trend is still climbing into its most recent week, with
  no decline to measure yet.
* `unknown` — the metric could not be computed at all: no peak was found,
  the peak was `0`, or there were no usable weeks. This is the only one of
  the four that means missing data.

See `fashion_trends.metrics.decay` for the implementation.
