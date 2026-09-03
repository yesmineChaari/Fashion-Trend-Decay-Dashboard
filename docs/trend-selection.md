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

### Choosing the anchor keyword

The anchor (`Settings.anchor_keyword`, included in every batch) needs measured
volume, not an assumed one — the same rule as everything else in this file. A
first instinct was a generic wardrobe-staple noun, on the theory that it would
be moderate and flat. Probing candidates against live Google Trends
(2021-09-01..2026-09-01, `geo=US`) showed the opposite: every generic
garment/shopping noun tried inherits the same spring-2026 artifact described
above, spiking to its all-time maximum on an arbitrary week that has nothing
to do with fashion.

| Candidate | 2026 peak week | Peak value | 2021-2025 typical | Verdict |
| --- | --- | --- | --- | --- |
| `little black dress` | 2026-04-12 | 100 | 29-38 | Rejected — artifact week |
| `personal style` | 2026-04-12 | 76 | 9-23 | Rejected — same artifact week |
| `vintage fashion` | 2026-04-12 | 100 | 6-8 | Rejected — same artifact week |
| `street style` | 2026-02-08 | 100 | 31-36 | Rejected — artifact week |
| `capsule wardrobe` | 2026-02-08 | 83 | 15-23 | Rejected — artifact week |
| `sustainable fashion` | 2026-02-08 | 38 | — | Rejected — artifact week |
| `thrift shopping` | 2025-12-28 | 6 | — | Rejected — too low-volume to resolve against |
| `haute couture` | 2026-07-05 | 100 | 28-53 | **Kept** — see below |

`haute couture` was the only candidate whose tallest weeks land on a real
calendar event instead of the artifact: its top weeks fall in January and
July every year (2022-07-03: 50, 2023-01-22: 53, 2024-01-21: 51, 2026-07-05:
100), matching the actual Paris Haute Couture Fashion Week schedule. It is
dense every week of the window (262/262 non-zero) and moderate in magnitude
(mean 23.5, min 14), putting it in the same order of magnitude as most
catalog entries rather than being dominated by them.

It is not perfectly flat — couture week itself roughly doubles it twice a
year, and 2026 is somewhat elevated versus 2022-2025 even accounting for
that. But the rescaling in `fashion_trends.ingest.batching.rescale_batches`
only uses the anchor's measured *peak* within each batch, and a real,
recurring seasonal high still gives a reliable reference point — unlike an
artifact spike shared with keywords that have nothing to do with fashion.

A live run of `collect_normalized_trends` against `mob_wife`, `demure`, and
`labubu` (each `isolate`-flagged trend gets its own anchor pairing) rescaled
both mega-trends to the same peak, even though this file's own measurements
put `demure` at roughly 2x `labubu`'s magnitude. That is the anchor
crush-to-a-handful-of-integers limit described in `Settings.anchor_keyword`
showing up in real data, not a bug: the anchor's raw reading in both solo
batches rounded to the same small integer, so the ratio derived from it
can't distinguish the two mega-trends' relative size. Their individual decay
shapes are unaffected — this only limits comparing mega-trends' magnitude
*to each other*, which is exactly why raw per-batch values are always kept.

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

`pytrends`, pinned in `requirements.txt`, was archived in April 2025, which had
been assumed to mean its session/cookie bootstrap no longer matches Google's
current flow. A live smoke test on 2026-09-03 against `pytrends==4.9.2` disproved
that: a normal fetch, an unknown-keyword fetch, and a second consecutive fetch
all succeeded with no HTTP 429, through the same client wrapper
(`src/fashion_trends/ingest/pytrends_client.py`) the rest of the pipeline uses.
The archived status is still worth watching — an unmaintained package can break
again without notice — but there is no known live-request failure today, and no
client swap is warranted unless one resurfaces.
