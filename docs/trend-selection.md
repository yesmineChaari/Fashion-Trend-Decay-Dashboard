# Trend selection

How the keywords in `config/trends.yaml` were chosen, what was rejected, and the
data-quality limits that constrain any metric built on top of them.

Every claim below comes from probing live Google Trends over
**2021-09-01 .. 2026-09-01, `geo=US`, weekly granularity** — the same window and
resolution the pipeline uses.

## Why the catalog changed

The first catalog was assembled from editorial memory of which trends went viral.
Probing it showed most of its keywords carry almost no search volume:

| Symptom | Keywords |
| --- | --- |
| No data returned at all | `balletcore aesthetic`, `blokecore aesthetic`, `balaclava fashion trend` |
| >90% of weeks are zero (curve is noise) | `cargo pants trend`, `coastal grandmother aesthetic`, `bow trend fashion`, `tomato girl aesthetic`, `indie sleaze fashion`, `bucket hat trend`, `chunky sneakers trend`, `e-girl aesthetic`, `micro bag trend`, `platform shoes trend`, `sheer layering fashion` (100% zero) |
| Usable density | `strawberry dress`, `low rise jeans`, `clean girl aesthetic`, `old money aesthetic` |

The cause is keyword construction, not trend choice. Appending `trend`, `fashion`
or `aesthetic` to a term collapses its volume — people search the trend's name, not
the trend's name plus a category word. Dropping the suffix recovers the signal:
`bucket hat trend` is 99% zeros, `bucket hat` is 0%. `balaclava fashion trend`
returns nothing, `balaclava` returns a full six-year curve.

Suffixes are not banned, only unverified ones. `clean girl aesthetic`,
`old money aesthetic` and `coquette aesthetic` all carry real volume with the
suffix attached, and are kept in that form.

## Selection rules

1. **Distinctive named term.** A term that means the trend and nothing else.
2. **Measured volume.** The keyword must return a dense weekly curve, judged
   against a shared anchor keyword so magnitudes compare across batches.
3. **A peak that matches a real date.** If the measured peak week cannot be tied
   to a known event or season, the curve is noise.
4. **Archetype coverage.** The set has to span flash fads, seasonal cycles,
   plateaus and revivals, not just the fastest decays.

## The 2026 artifact — the most important constraint

Generic commercial nouns all peak in the same few weeks of spring 2026,
regardless of subject:

| Keyword | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
| --- | --- | --- | --- | --- | --- | --- |
| cargo pants | 36 | 55 | 63 | 45 | 36 | **100** |
| ballet flats | 10 | 13 | 26 | 26 | 42 | **100** |
| leopard print | 49 | 38 | 35 | 63 | 67 | **100** |
| boat shoes | 28 | 40 | 36 | 73 | 42 | **100** |
| coffee maker | 50 | 51 | 50 | 45 | 52 | **100** |
| washing machine | 54 | 61 | 60 | 62 | 84 | **100** |
| lawn mower | 45 | 83 | 74 | 72 | 72 | **100** |

(yearly maximum of the weekly series, each keyword self-normalised to 100)

`coffee maker` and `lawn mower` are the control group. They have nothing to do
with fashion and show the same spring-2026 level shift, so this is a property of
Google Trends' 2026 data for broad commercial queries — not a fashion signal.

Consequences:

- **Any garment noun will be labelled "peaking now."** `cargo pants`,
  `ballet flats`, `boat shoes`, `butter yellow`, `barrel jeans`, `capri pants`,
  `wide leg jeans`, `low rise jeans` and `platform shoes` were all rejected for
  this reason, which is why the catalog currently has no `garment` entries.
  This is a limit of the method, not an oversight: a garment noun measures
  shopping demand and seasonality, not the life of a trend.
- **Distinctive names are immune.** `mob wife`, `demure`, `labubu`,
  `brat summer` and `mocha mousse` show no 2026 inflation, because nobody
  searches them for reasons unrelated to the trend.
- **Rejected on this rule despite being real trends:** `gorpcore` (20, 57, 55,
  36, 46, **100**), `balletcore` (0, 12, 14, 10, 9, **100**), `quiet luxury`
  (2, 4, 34, 22, 42, **100**), `strawberry dress` (7, 10, 7, 21, 8, **100**),
  `butter yellow` (6, 7, 8, 11, 39, **100**). Their measured peaks land on the
  artifact weeks, so their decay cannot be trusted.

Losing `quiet luxury` also removes the "hasn't peaked yet" lifecycle path the old
catalog carried. `bag_charm`, whose second rise is genuine but partly inflated,
is the nearest replacement and is flagged as such.

## Rejected for low volume

Real trends whose curves are too thin to measure, with peak height expressed as a
multiple of the `mob wife` peak:

| Keyword | Relative peak | Note |
| --- | --- | --- |
| `blokecore` | 0.03x | 21 non-zero weeks out of 261 |
| `eclectic grandpa` | 0.05x | 2 non-zero weeks |
| `tenniscore` | 0.05x | 2 non-zero weeks |
| `wrong shoe theory` | — | 99% zeros |
| `recessioncore` | — | no data returned |
| `e-girl` | 0.14x | peak sits at the window edge |
| `indie sleaze` | 0.12x | measured peak (2024-08) does not match its 2022 revival |
| `tomato girl` | 0.37x | contaminated by seasonal produce searches |
| `dopamine dressing` | — | 66% zeros, peak week is noise |

## Normalisation: batching is not free

Google Trends normalises each request to the largest keyword in it. `demure` and
`labubu` are roughly 130x and 66x the `mob wife` peak, and when either shares a
request with smaller terms, those terms round to zero — `coquette aesthetic`
returns a usable curve alone and a flat zero line next to `demure`.

Batches must therefore group keywords of comparable magnitude, with an anchor
sized to the group. The two mega-terms should be fetched alone and stitched in
through a shared anchor rather than batched with the rest.

## Window and geography

- **Five years is the maximum window that still returns weekly data.**
  `2021-09-01 .. 2026-09-01` gives 261 weekly points; widening it to six years
  silently drops the series to monthly, which is too coarse for decay rate or
  time-to-half measurement.
- **`geo=US` is the default.** Peak weeks are identical between US and worldwide
  for every keyword tested, but the worldwide series has lower resolution for
  Anglophone aesthetics — `coquette aesthetic` is measurable in the US series and
  flat worldwide.

## Client library

`pytrends`, pinned in `requirements.txt`, was archived in April 2025. Its session
bootstrap no longer acquires the cookie Google's current flow expects, so the
first data call returns HTTP 429 regardless of rate limiting. The Google Trends
endpoint itself is fine — every figure in this document was fetched from it. The
data source is unchanged; only the client needs to be one that is still
maintained.
