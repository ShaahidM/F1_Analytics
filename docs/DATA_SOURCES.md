# Data Sources — Verified Findings

All facts below were verified by direct requests on **2026-11-14** unless marked otherwise.
Re-verify before relying on anything marked *unverified*.

## Critical change: F1 archive lockdown (Oct 2026)

Since ~15 Oct 2026, `livetiming.formula1.com/static/*` returns **HTTP 401** for every season
(verified: 2019 + 2024 `Index.json`, 2024 `CarData.z.jsonStream`). The FastF1 maintainer
confirms an **F1 TV Access (paid) subscription** is now required
([FastF1 #978](https://github.com/theOehrly/Fast-F1/issues/978)). FastF1 ≥3.9 supports login via
`F1_USERNAME` / `F1_PASSWORD`; without them it loads nothing (verified with 3.9.2 on 2019 Bahrain).
F1's terms forbid rehosting this data. `livetiming-mirror.fastf1.dev` only has 2021–2022 (2019/2020 → 404)
and is not used, because of those terms.

**Decision (user, 2026-11-14): no F1 TV subscription.** FastF1 is therefore not a data source for now.
The `sources/` adapter interface leaves room to add it later.

The research doc (`IntialResearch.md`) predates this change and is wrong on several points:
- FastF1 *does* provide X/Y/Z position (not just "normalized track position").
- FastF1 is *not* 10–20 Hz; both sources expose the same F1 feed (car ≈ 3.7 Hz, position ≈ 4 Hz).
- MultiViewer (used by FastF1's `get_circuit_info`) gives corner X/Y, not just names.

## Capability matrix

| Season    | Telemetry | Racing line (x/y) | Lap + sector times | Compound / tyre age | Pit stops | Weather / flags | Source |
|-----------|-----------|-------------------|--------------------|---------------------|-----------|-----------------|--------|
| 2023–now  | ✅        | ✅                | ✅ (+ speed traps)  | ✅ (from stints)    | ✅        | ✅              | OpenF1 |
| 2019–2022 | ❌        | ❌                | lap times only (no sectors) | ❌         | ✅        | ❌              | Jolpica |

Each session's capabilities are computed at runtime and returned by the API, and the UI disables
features that a session can't support. Don't hardcode by year.

## OpenF1 — `https://api.openf1.org/v1` (primary, 2023+)

- Free, no auth for historical data. **Rate limits: 3 req/s and 30 req/min** (official site).
  Live data is paid (€9.90/mo), but we don't need it.
- `?csv=true` is supported. Filters: `field>=x`, `date>…&date<…`.
- Still ingesting after the lockdown: 2026 São Paulo (session 11412, 2026-11-08) has full data.
- One driver's full-race `car_data` is ~29k rows / 4.9 MB JSON / ~3.5 s. `location` is similar (~1.9 MB CSV).
  Fetch **one driver per request, the full session once**, then cache it as Parquet. This uses far fewer
  requests than per-lap windows (30/min limit).

Verified fields:
- `sessions`: session_key, session_type ("Practice"/"Qualifying"/"Race"), session_name ("Race", "Qualifying",
  "Sprint", "Sprint Qualifying"/"Sprint Shootout"…), date_start, date_end, meeting_key, circuit_key,
  circuit_short_name, country_name, location, gmt_offset, year, is_cancelled
- `meetings`: meeting_key, meeting_name, meeting_official_name, location, country_*, circuit_key, circuit_short_name …
- `drivers`: driver_number, broadcast_name, full_name, name_acronym, team_name, team_colour (hex, no #),
  first_name, last_name, headshot_url, country_code
- `laps`: lap_number, date_start, duration_sector_1/2/3, i1_speed, i2_speed, st_speed, is_pit_out_lap,
  lap_duration, segments_sector_1/2/3 (mini-sector codes). There is **no compound and no pit-in flag** per lap.
  date_start/lap_duration can be null (e.g. lap 1, or after a pit stop).
- `car_data`: date, speed, rpm, n_gear, throttle (0–100), **brake (0 or 100, binary)**, drs (codes; **null in 2026**,
  because DRS was abolished by the 2026 rules)
- `location`: date, x, y, z (**units 1/10 m**, F1 frame). Early samples can be (0,0,0) and must be filtered.
  **⚠ The positions are map-matched to a fixed track model, not raw GPS** (verified 2023 Monza, 2024 Monza, 2026 São Paulo):
  every car/lap lies within ~0.5 m (p99) of any other car's lap with the *same signed offsets* at every corner. At the 2024
  Monza start, 20 cars on the staggered grid were all within ±0.2 m of one line. The pit lane is a separate path (~15 m off).
  ⇒ **Lateral racing-line differences between drivers cannot be measured from public data.** Position is still valid
  for *where along the lap* things happen (track distance), and for the map and relative car positions.
  Corroborated by [f1technical forum](https://www.f1technical.net/forum/viewtopic.php?p=913339): "all coordinates are on one line".
- `stints`: stint_number, lap_start, lap_end, compound, tyre_age_at_start
- `pit`: date, lap_number, pit_duration, lane_duration, stop_duration (often null)
- `intervals` (races): date, interval, gap_to_leader (~every 4 s), used for traffic detection
- `position`: date, position
- `race_control`: date, lap_number, category ("Flag", "SafetyCar", "Other", …), flag, scope, sector,
  qualifying_phase, driver_number, message
- `weather`: date, air_temperature, track_temperature, humidity, pressure, rainfall, wind_speed, wind_direction (~1/min)
- `session_result`: position, number_of_laps, points, dnf, dns, dsq, duration, gap_to_leader
- `overtakes`: overtaking_driver_number, overtaken_driver_number, date, position
- `team_radio`: recording_url only (no transcripts; URLs point at the now-401 F1 archive, so they may not play)
- `starting_grid`: returned no results for 2024 Monza (*incomplete, don't rely on it*)

Sample spacing: car_data ≈ 160–440 ms (p5–p95, median 240 ms, gaps up to ~1 s), location ≈ 220–280 ms.
At 300 km/h one sample ≈ 20 m, which limits braking-point precision. car_data **timestamps jitter**: we've seen impossible
jumps (119→149 km/h in 0.28 s), so point derivatives are meaningless (see TYRE_METHODOLOGY.md §2).
OpenF1 lap `date_start` and the position-derived timing-line crossing differ by up to ~1 sample (~0.2 s).

## MultiViewer — `https://api.multiviewer.app/api/v1/circuits/{circuit_key}/{year}`

- No auth. Send the header `User-Agent: FastF1/3.9` (FastF1 does the same).
- Returns: corners[{number, letter?, angle, length (distance along lap), trackPosition{x,y}}], marshalSectors,
  marshalLights, x[]/y[] track outline, rotation (degrees, for map display), pitLoss, miniSectorsIndexes, year.
- `circuit_key` = OpenF1 `circuit_key`. **The coordinate frame matches OpenF1 `location` exactly**
  (Monza: x −1500…11069, y −5805…15892 in both).
- It may return an older layout year than the one requested (asked for 2024 Monza, got 2021). Third-party
  and unofficial, so it is optional enrichment; we fall back to detecting corners from speed minima.

## Jolpica-F1 (Ergast successor) — `https://api.jolpi.ca/ergast/f1/`

- Free, no auth. Schedule, results, qualifying, `laps` (lap times + positions, **no sectors and no compounds**),
  `pitstops` (lap, stop, time, duration), 1950+.
- Used for: the 2019–2022 season/event list, lap times and pit stops, and official classification.
- The published rate limit is roughly 4 req/s and 500/h (*unverified*). Paginate with `limit`/`offset` (max 100).

## Not available anywhere (public)

Tyre temperature, pressure, wear, remaining grip, brake pressure, steering angle, lateral g, fuel load,
ERS state, and team radio transcripts. Anything about these is **estimated or assumed**, never measured.
