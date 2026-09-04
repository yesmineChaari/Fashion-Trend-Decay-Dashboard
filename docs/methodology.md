# Methodology

How each metric in `metrics.parquet` is defined, so a reader comparing this
project's figures against any other source knows exactly what they mean.

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
is always excluded, whether by the caller having already dropped it (see
`fashion_trends.metrics.smoothing.preprocess_series`) or because it simply
isn't part of the completed weekly series yet.

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
