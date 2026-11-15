# Architecture

## Stack (decided 2026-11-14)

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | Python 3.13, FastAPI, Pandas, NumPy, SciPy (+ statsmodels later) | All the analysis lives in Python. FastAPI gives typed JSON and OpenAPI docs |
| Storage | **DuckDB + Parquet** (not PostgreSQL) | Local single-user tool. Historical telemetry is immutable and read in column slices. No server to run (Docker daemon not running). Sits behind the `storage/` interface, so Postgres can replace it if the app is ever hosted |
| HTTP | httpx + a rate limiter (OpenF1 3/s & 30/min) + on-disk raw cache | Historical data never changes, so we download it once |
| Frontend | Next.js (App Router) + TypeScript, TanStack Query, Zustand | Zustand holds the shared "cursor distance" that links the map, charts and corner views |
| Track map | Canvas 2D + d3-zoom | ~2–6 laps × ~1–5k points draws trivially. Canvas makes animation cheap. WebGL is unnecessary |
| Telemetry traces | uPlot | Several synced charts, fast cursor sync, ~50 KB. Plotly hover-sync across 6 charts is sluggish |
| Analysis charts | Plotly (react-plotly.js, plotly.js-dist-min) | Scatter + fits + CI bands, box plots, strategy timelines |

## Repo layout

```
backend/
  app/
    main.py            FastAPI app, CORS for localhost:3000
    config.py          paths, rate limits, constants (no data hardcoded)
    api/               routers: catalog, session, telemetry, analysis
    sources/           one adapter per external source, all return normalized DataFrames
      base.py          SessionSource protocol + Capabilities
      openf1.py        2023+ (primary)
      jolpica.py       schedule/results/laps/pitstops (2019–2022 fallback)
      multiviewer.py   corners / outline / rotation (optional enrichment)
      registry.py      picks a source per season from capabilities, not hardcoded years
    storage/
      cache.py         raw response cache + Parquet store (data/), DuckDB queries
    processing/
      laps.py          lap table normalization: compound/tyre age from stints, track status, clean-lap flags
      telemetry.py     merge car+pos by time, slice laps, distance, accel
      reference.py     reference line, projection (s, lateral offset), distance grid resampling
      corners.py       corner s-positions, zones, per-corner metrics
    analysis/          degradation.py, style.py, preservation.py, strategy.py (Phases 2–4)
  tests/
frontend/            Next.js app
data/                (gitignored) raw/ + parquet/ caches
docs/                these docs
```

## Normalized data model (internal; independent of source)

- `Session`: key, year, meeting_name, session_name, session_type, circuit_key, date_start, source, capabilities
- `Driver`: number, code, name, team, team_colour
- `Lap`: driver, lap_number, lap_start (UTC), lap_time_s, s1/s2/s3, i1/i2/st speed, compound, tyre_age,
  stint, is_pit_out, is_pit_in, track_status flags (sc, vsc, yellow, red), deleted, in_traffic, clean, exclude_reason
- `Telemetry` (per driver, per session; Parquet): t (UTC), speed, throttle, brake, gear, rpm, drs, x, y, z
- `LapTrace` (computed per request, cached): s (m on the reference grid), t_rel, speed, throttle, brake, gear, rpm,
  drs, x, y, accel_long, lateral_offset
- `Corner`: number, letter, s_apex, x, y, angle, zone_start, zone_end
- `Capabilities`: telemetry, position, sectors, compounds, pit, weather, race_control, intervals (booleans)

## Lap alignment (the core of every comparison)

Timestamps aren't comparable across laps, so everything is aligned on **track distance `s` from the reference line**:
1. **Reference line**: the fastest clean lap in the session (any driver), resampled to 1 m spacing with cumulative s.
2. **Projection**: every x/y sample is projected onto the nearest reference segment (scipy cKDTree + segment
   projection), giving `s` and a signed `lateral_offset`. The start/finish wrap is unwrapped to keep s monotonic.
   This avoids the drift of integrating speed (FastF1's approach) and gives every lap the same corner positions.
3. **Car data** has no x/y, so it gets `s` by time-interpolating the position stream.
4. **Resampling**: onto a common 5 m grid (sample resolution is ~7–20 m, so 5 m is lossless enough).
   Continuous signals are linear-interpolated. Gear, brake and DRS use previous-value.
   The raw samples stay available so the UI can show actual data points.
5. **Elapsed time t(s)**: position timestamps jitter ±~0.05 s locally, and integrating speed drifts, so
   t(s) = ∫ds/v + (400 m moving average of [t_pos − ∫ds/v]). Noise std 0.006 s. End-of-lap Δ matches the official
   lap-time difference within ~20 ms (Monza 2024 check). **Delta time**: Δt(s) = t_B(s) − t_A(s).
6. **Corners**: MultiViewer corner (x,y) projected onto the reference → s. Fallback: local speed minima.
7. **Corner zones** (`analysis/corners.py`): speed minima (prominence ≥ 10 km/h) on the reference lap. A zone runs from
   the approach speed peak to the exit speed peak, is labelled with the corners inside it (e.g. "T1–T2"), and is
   **shared by every lap in the session**, so time-in-zone compares identical track. Corners outside any braking zone
   become "flat" zones (±150/100 m).

## Data flow / caching

```
request → registry picks source → storage.cache hit? → else source fetch (rate-limited) → normalize → Parquet
                                                                      ↘ analysis (pure functions on DataFrames) → JSON
```
- Raw telemetry is fetched for a **whole session, per driver** (2 requests per driver), never per lap.
- Parquet files live at `data/parquet/{source}/{session_key}/{table}[_{driver}].parquet`.
- Catalog responses (seasons, sessions) are cached with a TTL for the current season and permanently for past seasons.
- Every API response carries `provenance` (source, evidence tier) and `capabilities`.

## Season comparison (`processing/season.py`)

Two drivers are chosen by **code** (car numbers change between seasons). A background job walks every finished
Grand Prix of the season and builds a per-race summary with the same session-level code (Model B tyre slopes, a
paired like-for-like pace gap, style medians, preservation pattern counts, line-length significant zones).
Each summary is cached as JSON (for the UI) and a long-format Parquet of metrics; the season scorecard is a DuckDB
query over `data/season/{year}/{A}_{B}/*.parquet` (median per driver × metric, dry races only unless asked).
Cost: ~13 OpenF1 requests per race (~300 per season, 10–15 min cold at the free limit); traffic uses the
classification-interval fallback to avoid ~500 extra requests.

## Comparison modes

`same_lap` | `same_tyre_age` | `fastest` | `custom`. Each returns a `comparability` object listing the differences
(compound, tyre age, lap number / fuel proxy, traffic, track status). The UI shows a "not directly equivalent"
banner when any of these differ.

## Roadmap

- **Phase 1 (foundation)**: catalog (year → GP → session), drivers, normalized laps/stints, telemetry cache,
  reference-line alignment, track map with two racing lines (speed colouring), comparison-mode lap picker.
- **Phase 2**: animated replay (play/pause/scrub), synced uPlot telemetry + delta, corner zoom + corner table,
  multi-lap overlay, degradation charts (Model A).
- **Phase 3**: driving-style profile, preservation indicators P1–P9, pace-vs-preservation view, Model B.
- **Phase 4**: strategy timeline, pit loss (MultiViewer pitLoss), undercut/overcut analysis, cross-compound view.
