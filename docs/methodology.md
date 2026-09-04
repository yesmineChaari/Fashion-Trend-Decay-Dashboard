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
