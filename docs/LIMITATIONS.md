# Known Limitations

Everything below was found during development (2026-11-14) and is either a hard data limit, a methodological
choice, or an engineering gap. Update this file when a limitation is removed or a new one is found.

## 1. Data access
1. **2019–2022 has no telemetry, positions, sector times or tyre compounds.** F1's timing archive needs an F1 TV
   subscription since ~15 Oct 2026; the user has none, so these seasons use Jolpica (lap times + pit stops only).
2. **2019–2022 tyre age is inferred** (assumes a new set at the start and at every stop) and compounds are unknown.
3. **2019–2022 has no race-control data**, so SC/VSC/red-flag laps can't be detected. They're removed only if they fail
   the lap-time outlier test (e.g. Bahrain 2019's final SC lap of 120 s was not removed).
4. **2019–2022 qualifying and sprints have no lap-by-lap times** in Jolpica (results only).
5. **OpenF1 is community-run and unofficial**: availability or schema can change. Free tier is 3 req/s and 30 req/min, so
   cold loads are slow; live data (paid) is not supported.
6. **MultiViewer is unofficial**: corner markers can come from an older layout (falls back to speed-minimum corners when
   they don't match), and its pit-loss figures are third-party estimates.
7. **No public source has** tyre temperature, pressure, wear or grip, brake pressure, steering angle, lateral g, fuel load,
   ERS state or set-up. Team-radio transcripts don't exist publicly (OpenF1 only links audio on the locked archive).

## 2. Telemetry quality
8. **Positions are map-matched to one track line**, so the racing line can't be drawn and per-lap line differences aren't
   measurable. The map draws traces offset for visibility only. *Partial workaround (experimental)*: extra distance
   driven per corner (wheel-speed integral minus track distance) averaged over a session detects consistent differences
   of ≳ 3 m, but it can't separate a longer line from more tyre slip (wheel speed is affected by slip).
9. **~4 Hz sampling** (~20 m between samples at 300 km/h): brake points are ±7–20 m, events shorter than ~0.3 s are
   missed, quick gear shifts can be missed, and wheelspin can't be detected (feature dropped).
10. **Brake is on/off only**: no pressure or trail-braking intensity. Braking intensity is a kinematic estimate.
11. **car_data timestamps jitter** (gaps up to ~1 s), so acceleration is smoothed over ~1.7 s and underestimates peaks
    (≈ −3 g against a real ~−5 g). Mean braking deceleration (≈ −2.4 to −2.9 g) is also below true values.
12. **Elapsed time along the lap** combines speed integration with a 400 m low-pass correction to position timing. Local
    noise is ~0.006 s and the end-of-lap delta is within ~0.02 s of official, but a trace's lap time can differ from the
    official one by up to one sample (~0.2 s).
13. **Alignment depends on the reference lap** (fastest lap with complete position data). Its length is the racing-line
    length (~0.5% shorter than the official circuit length). Laps with telemetry gaps are flagged, not repaired.
14. **2026+ cars**: DRS is null, and energy management heavily affects throttle, coasting and straight-line speed, which
    confounds those indicators.

## 3. Lap classification
15. **SC/VSC/red windows are reconstructed heuristically** from race-control messages (SC ends one typical lap after
    "IN THIS LAP", VSC 20 s after "ENDING", red one lap after the next green). Laps at the boundaries can be mis-flagged.
16. **Traffic now uses every car's on-track position** (racing cars, backmarkers, blue flags). The first time a session
    is opened it needs a background download (~20 requests, ~30–60 s). Until then the classification-interval fallback
    is used, which can't see backmarkers. Gaps are converted with the car's own speed, so they're approximate (±0.5 s
    against OpenF1 intervals). It doesn't capture dirty-air effects beyond 1.5 s or the car behind except for blue flags.
    (Fixed: OpenF1 reports the leader's interval as 0, which used to flag every lap led as traffic.)
17. **Yellow flags aren't mapped to track position**: any yellow anywhere during the lap soft-flags it.
18. **The outlier filter (5 × MAD per stint) doesn't detect car problems**: damage or engine issues (e.g. LEC, Bahrain
    2019) stay in the data and look like "degradation".
19. **Qualifying push laps** are defined heuristically (≤ 107% of the driver's own best).
20. **Deleted-lap detection parses race-control text**; a wording change would break it.
21. **Rain and changing conditions aren't modelled**: inters/wets are treated as compounds; only track temperature
    enters Model B.

## 4. Corner analysis
22. **Corner zones come from speed minima** (≥ 10 km/h prominence) on the reference lap and run from the approach peak to
    the exit peak, so "time in zone" includes some straight. Chicanes are grouped; flat-out corners only get minimum
    speed and throttle.
23. **Brake point and throttle pickup are measured relative to the reference apex**, not each lap's own apex.
24. **Thresholds are analyst choices**: coasting = throttle < 5%, brake off, > 150 km/h; pickup = 20%; full = 98%.

## 5. Statistical models
25. **Model A (per stint)** mixes fuel burn, track evolution and tyre degradation (inseparable within one stint). The fuel
    slider is an assumption.
26. **Model B (session-wide)** assumptions:
    - γ (fuel + track) is linear and common to all drivers;
    - tyre age is linear within a compound;
    - compound and driver offsets are constant;
    - HC3 standard errors ignore lap-to-lap autocorrelation, so CIs are probably too narrow;
    - compound offsets are confounded with race phase when compounds are used at different times (shown as a warning;
      e.g. Monza 2024 says fresh Mediums are 0.27 s slower than Hards);
    - a driver with a single stint relies entirely on γ;
    - it needs ≥ 30 clean laps and runs for races only.
27. **Preservation labels are rule-based interpretations with no ground truth.** Thresholds (≈ measurement resolution)
    reduce but don't eliminate false positives from ~7 zones × 9 indicators × stints. Fuel burn biases trends (lighter car
    → later braking, more speed). The rule was already revised once, when "braking earlier" was found to be ambiguous.
28. **Driving-style differences** reflect the car and set-up as much as the driver; teammate comparisons are fairest.
29. **Qualifying** has too few laps per tyre set for any tyre-age trend.

## 6. Strategy
30. **Gaps use line-crossing timestamps** (OpenF1) or cumulative lap times (Jolpica, grid offset ignored). Monza 2024's
    final LEC–PIA gap was computed as 2.58 s against the official 2.66 s.
31. **Positions are crossing order**, so post-race time penalties are not reflected.
32. **Pit loss** = in-lap + out-lap − 2 × the driver's nearby clean-lap median, so the baseline laps differ in fuel, tyres
    and traffic. Stationary time is usually missing from the feed (OpenF1 `stop_duration` null).
33. **Undercut/overcut** covers only the selected pair and stops within 6 laps of each other. "On-track difference" mixes
    the fresh-tyre gain with traffic and old-tyre pace. There is no counterfactual simulation.
34. **Cross-compound curves** extrapolate beyond the ages a driver actually ran, using field-wide slopes.

## 7. Platform / engineering
35. **Local, single user, no authentication.** Caches live in `data/` and in-process LRU memory (restart to clear).
36. **First loads are slow** (rate limits; style/preservation compute every clean lap, ~4–6 s per session pair).
37. **`uvicorn --reload` in the OneDrive folder sometimes misses new routes**; OneDrive also syncs `node_modules`,
    `.venv` and `data/`.
38. **Dark theme only, desktop layout only.** There are no data-table alternatives for most charts, and Plotly adds ~3.5 MB.
39. **DuckDB is installed but unused** (Parquet is read with pandas).
40. **No automated UI tests in the repo** (Playwright checks were run ad hoc). Backend has 17 offline unit tests.
41. **Limited sessions verified by hand**: 2024 Monza race and qualifying, 2023 Monza and Australia, 2026 São Paulo,
    2019 Bahrain. Street circuits, Suzuka's crossover, sprint sessions and red-flag restarts haven't been visually checked.
42. **Practice and live sessions are out of scope.** FP2 long runs could add controlled per-compound degradation data
    (fuel loads and engine modes are unknown, so they can't feed Model B directly). Candidate next phase.
43. **2019–2022 is hidden by default** (a switch shows it): those seasons support lap times, degradation trends and
    strategy only.
44. **Tyre-age views (degradation, pace vs preservation, strategy) are disabled for qualifying**: 1–3 push laps per set.
