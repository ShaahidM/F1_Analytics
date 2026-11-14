# Tyre Management — Methodology

Goal: help answer *where, how and potentially why one driver gives up immediate lap time to preserve tyres
compared with another*, without making up data that doesn't exist.

## 1. Evidence tiers (must be shown in the UI on every metric)

| Tier | Badge | Meaning | Examples |
|------|-------|---------|----------|
| MEASURED | `M` | Value straight from the feed (resampled only) | speed, throttle, brake on/off, gear, RPM, x/y, lap and sector times, compound, tyre age |
| CALCULATED | `C` | Deterministic derivation from measured data, with a stated resolution | distance, longitudinal accel, brake-onset point, min corner speed, full-throttle %, coasting distance |
| ESTIMATED | `E` | Output of a statistical model, shown with an uncertainty interval | degradation rate (s/lap), fuel-corrected pace, tyre-age effect |
| INTERPRETATION | `I` | A hypothesis the data is *consistent with*. Never shown as fact | "pattern consistent with tyre management" |
| ASSUMPTION | `A` | An unverified input chosen by the analyst, not derived from data | fuel-burn s/lap, tyre age inferred from pit stops (2019–22) |

Forbidden: presenting anything as tyre wear, grip remaining, tyre temperature or "% tyre life".

## 2. What the data can and cannot resolve

- **Brake is binary (0/100)**, so there is no brake pressure. Braking *intensity* is the deceleration calculated from
  speed (tier C).
- **Sample spacing is ~0.25 s**, which is ~20 m at 300 km/h and ~7 m at 100 km/h. Brake onset is interpolated between
  samples, and every braking-point value carries a ± resolution equal to half the local sample spacing in metres.
  Differences below the resolution are shown as "not resolvable".
- **Position (x/y) is map-matched to a track model** (see DATA_SOURCES.md), so **lateral line choice is NOT observable**.
  "Racing line" analysis means *longitudinal* behaviour along the line: where braking, lifting, throttle pickup and
  minimum speed happen, and at what speed. The map shows two drivers' traces offset for visibility and labels them that way.
- **Acceleration**: car_data timestamps jitter, so acceleration comes from a local quadratic fit over 7 raw samples (~1.7 s).
  Instantaneous g is **smoothed and underestimates peaks** (Monza T1 shows ≈ −3.1 g against a real ~−5 g). For braking
  intensity use **mean deceleration over the braking zone** = (v_onset − v_min) / (t_min − t_onset), which is robust to jitter.
- **Wheelspin**: a rise in RPM without a matching rise in speed in a fixed gear can *suggest* it, but at ~4 Hz it is
  unreliable. It is marked experimental and off by default.
- **2026+ cars**: there is no DRS (`drs` is null), and energy management (deployment limits, lift-and-coast for harvesting)
  strongly affects speed at full throttle and coasting. Throttle and coasting indicators are confounded with ERS strategy,
  and the UI must say so for 2026+ sessions.

## 3. Lap eligibility (the "clean lap" filter)

A lap enters the pace and degradation analysis only if all of these hold, and every exclusion is shown with its reason:
1. Not lap 1, not a pit-out lap (`is_pit_out_lap`), not a pit-in lap (the lap before a stint change or `pit.lap_number`).
2. No SC/VSC/red during the lap window, reconstructed from `race_control` (SC window ends one typical lap after
   "IN THIS LAP", red ends one lap after the next green light, VSC ends 20 s after "ENDING"). **Yellow** flags (marshal
   sector level) are a *soft flag* only, because almost every race lap has one somewhere.
3. Not deleted (race_control messages "LAP … DELETED" for that driver).
4. Same weather regime (no `rainfall` change; compound not INTERMEDIATE/WET unless the analysis is wet-only).
5. Traffic: flagged (not dropped). **Primary method (`processing/traffic.py`)**: every car's position is projected to
   cumulative race distance; each second the nearest car physically ahead is found and its distance is turned into a
   time gap with the car's own speed. The lap relation classifies it as a racing car, a **lapped backmarker**, or a car
   lapping ahead; a car ≥ 1 lap up within 1 s behind means "being lapped (blue flags)". Pit-lane cars (lateral offset
   > 8 m) are ignored. Validated on Monza 2024: correlation 0.95 with OpenF1 `interval` for same-lap cars, plus 39
   backmarker laps that intervals missed. It runs in the background (every car's positions, ~20 requests); until it
   finishes, the fallback is the classification `interval` < 1.5 s (leader's interval of 0 treated as missing: fixed bug).
6. Robust outlier filter: |lap − stint median| > 5 × MAD, flagged and excluded by default.

## 4. Degradation model (ESTIMATED)

**Identifiability problem:** within a single stint, tyre age and lap number both go up by 1 each lap, so fuel burn
and track evolution are **perfectly collinear** with tyre age. One stint alone can't separate them.
Tyre age *resets* at pit stops while lap number doesn't, so a model fitted over many stints can.

Model A, per-stint robust fit (descriptive):
`lap_time = a + b·tyre_age (+ c·tyre_age²)` with a Theil–Sen or Huber fit and a bootstrap 90% CI.
`b` is labelled **"raw pace trend (fuel + track + tyre combined)"**, not degradation.

Model B, session-wide fixed-effects regression (inferential):
```
lap_time_ij = α_driver(i) + κ_compound + γ·lap_number + Σ_compound β_c·tyre_age·[compound=c] + δ·track_temp + ε
```
- Fitted on all clean laps from all drivers in the race (more drivers means better identification of γ).
- γ captures fuel burn plus track evolution together. They can't be split without external information.
- β_c is the **estimated tyre-age effect per compound** (s/lap), reported with a CI.
- κ_compound is the fresh-tyre pace offset per compound (added in Phase 4). It is confounded with race phase when a
  compound is mostly used early or late, which triggers an automatic warning. Model B predictions at a common
  reference lap and temperature drive the cross-compound view.
- A driver-specific slope (β_c + β_c,driver) is the comparison metric between the two drivers.
- Option: a fuel-correction prior (default ~0.03 s/kg × burn kg/lap, both **ASSUMPTIONS**, editable, shown as sliders)
  for Model A only, so the user can see how sensitive the result is to the assumption.
- Diagnostics shown: n laps, R², residual plot, and a warning when a driver has fewer than 2 stints (identification is weak).

**Cross-compound comparison:** compare β_c and the intercept at equal tyre age, never raw lap times. The UI shows a
"not directly equivalent" banner listing the differences: compound, tyre age, lap number (fuel), traffic, track status.

## 5. Preservation indicators (CALCULATED per lap, then trended vs tyre age)

All computed per corner or zone on the distance-aligned lap, then regressed against tyre age within a stint.
The *change with tyre age* and the *difference between drivers at equal tyre age* are what matter, not absolute values.

| # | Indicator | Calculation | Plausible tyre link | Alternative explanations to show |
|---|-----------|-------------|---------------------|----------------------------------|
| P1 | Brake-onset distance before apex | interpolated brake 0→100 point relative to the corner apex | earlier braking = less entry load | fuel load, brake temps, traffic, wind, ERS harvest (2026) |
| P2 | Peak and mean deceleration in the braking zone | −dv/dt over the zone | gentler = less front load | lower entry speed, fuel |
| P3 | Entry speed / minimum speed / exit speed | speed at fixed distances around the apex | lower min speed = less lateral load | grip loss *caused by* wear (inverse causation!), wind, traffic |
| P4 | Throttle pickup | distance from apex to first throttle > 20%, and to 100% | later or gentler = less rear slip | traction loss from wear, kerb use, line |
| P5 | Throttle ramp rate | d(throttle)/ds from pickup to full | progressive = rear preservation | as P4 |
| P6 | Coasting distance | throttle < 5% and brake = 0 at > 150 km/h | lift-and-coast = saving tyres, brakes or fuel | **fuel saving, brake cooling, ERS harvest (esp. 2026)**, so it is never attributed to tyres alone |
| P7 | Full-throttle fraction | % of lap distance with throttle ≥ 98% | lower = managing | traffic, DRS/aero, 2026 energy |
| P8 | Extra distance driven (EXPERIMENTAL) | ∫ wheel speed dt (calibrated per lap so the whole lap = track length) minus track distance through the zone | longer line **or more tyre slip**; rising slip with tyre age would be a wear signal | line choice, wheel-speed sensor slip, traffic; per-lap noise ~4–7 m, so only session averages or stint trends are usable |
| P9 | Sector-time drift vs tyre age | per-sector Model A slope | where the time loss concentrates | as Model A |

**The key interpretation rule: voluntary vs forced slowdown** (implemented in `analysis/preservation.py::classify`).
Wear *forces* lower corner speeds (less grip). Management is a *choice* to lift, coast or feed the throttle in
while corner speed holds. **Braking earlier on its own is ambiguous**: it also happens when grip is lost (the
original draft of this rule got that wrong), so it only counts alongside maintained minimum and exit speed.

A trend "counts" only when its 90% CI excludes zero **and** the change across the stint's tyre-age span reaches a
practical threshold (`MIN_CHANGE`, roughly the measurement resolution: brake point 10 m, speeds 2–3 km/h, coasting
and throttle distances 10 m, decel 0.15 g, zone time 0.05 s). This limits false positives from testing ~7 zones ×
9 indicators per stint.

- *Consistent with management*: coasting ↑; or throttle ramp ↑ with min/exit speed not ↓; or brake point earlier
  with min/exit speed not ↓.
- *Consistent with grip loss*: min speed ↓ without extra coasting; or exit speed ↓ without a more progressive throttle.
- Both, giving *mixed*; neither, giving *no clear pattern*; fewer than 3 fitted indicators, giving *insufficient data*.
- These labels are tier I. The UI shows the supporting trends and the confounders: fuel burn (a lighter car brakes
  later and carries more speed, masking grip loss), track evolution, traffic, brake temperature, ERS strategy.

**Model B check (2024 Monza, 901 clean laps, 20 drivers):** the fitted lap effect γ = −0.056 s/lap [−0.062, −0.050]
agrees with the typical published fuel-burn estimate (~0.05–0.06 s/lap). Field tyre slopes: HARD +0.046, MEDIUM +0.061 s/lap.

## 6. Baselines for "pace sacrificed"

Estimated time cost per zone = the driver's own corner time on this lap − their own best corner time on the
**same compound and similar tyre age early in the stint** (or another baseline the user picks: quali lap, or the
other driver). Shown as ESTIMATED, because the baseline lap had a different fuel load.

## 7. Validation (honest limits)

- No public ground truth for tyre state exists.
- Sanity checks: indicators should spike on known management laps (e.g. one-stop races), and coasting should rise
  late in stints before a long run. Team-radio transcripts aren't available (OpenF1 only has audio URLs).
- Every chart has an "Assumptions & confounders" disclosure listing the active filters and assumption values.
