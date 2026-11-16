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
   > 8 m) and stationary cars (< 5 m/s: retired cars keep a frozen position) are ignored. Validated on Monza 2024:
   correlation 0.95 with OpenF1 `interval` for same-lap cars, plus 39 backmarker laps that intervals missed. "Being
   lapped" checked against the official blue-flag log (Monza, Monaco, Suzuka 2024): recall 96–100%, precision
   95–100% within ±1 lap. It runs in the background (every car's positions, ~20 requests); until it
   finishes, the fallback is the classification `interval` < 1.5 s (leader's interval of 0 treated as missing: fixed bug).
6. Robust outlier filter: |lap − stint median| > 5 × MAD, flagged and excluded by default.

### Practice sessions: long runs
In practice, laps enter trend analyses only if they belong to a detected long run (`processing/laps.py::long_run_mask`):
per driver and tyre set, laps within ±2.5% of the run's median pace (band re-centred once), at least 5 such laps,
including at least 3 consecutive. Alternating push/cool-down laps never qualify; slow laps before or after the run
don't disqualify it. Other laps get the exclusion reason "not part of a long run" but stay selectable for lap
comparison. Fuel loads and engine modes are unknown in practice, so only Model A (per-run trend) is fitted, and
trends should be compared within a driver or between teammates. Validated on Monza 2024 FP2 (16 drivers' runs),
Mexico 2026 FP2 (19) and rain-hit Australia 2023 FP2 (2).

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

## 8. Strategy what-if simulator (Stage A: lap-time maths)

Code: `analysis/race_model.py`, `analysis/simulator.py`; UI: Strategy tab → "What-if strategy simulator".

**Lap-time model** (dry races only, fitted on every driver's clean laps):
`lap = α_driver + κ_compound + γ·lap + β_c·age (+ q_c·age² if AIC improves, ≥ 100 laps) + δ_{d,c}·min(age, own max)`.
- Driver deviations δ are ridge-shrunk toward the field slope (Gaussian prior, SD 0.02 s/lap: an ASSUMPTION). That keeps
  the model identifiable and stops short stints producing wild slopes.
- Beyond a driver's own oldest tyre the field slope continues; beyond the field's oldest tyre the quadratic continues
  along its tangent. Both are flagged as extrapolation in the UI (2 laps of tolerance for in/out laps).
- A compound is "unreliable" with < 3 drivers, < 40 clean laps or a negative slope (e.g. Hungary 2025 Softs once fitted
  −0.19 s/lap). It's excluded from the optimiser and flagged in the builder.

**Simulation**:
- Lap 1 and red-flag restart laps are the driver's real times (starts aren't modelled).
- On real SC/VSC/red laps each driver keeps their own real lap time, with their real stop removed and the plan's stop
  charged instead. Pit loss is measured against the model (real in + out lap − model prediction) and split between
  in-lap and out-lap in the proportion measured in that race. Stops under a red flag are free (regulations); stops
  under SC/VSC use MultiViewer's SC/VSC loss.
- Uncertainty: 2,000 Monte Carlo draws of the coefficients (covariance), AR(1) lap noise and pit-loss spread.
  Strategies are compared on the same draws.
- **Anchoring**: what-if crossing time = real crossing time + (simulated plan − simulated real strategy). The real
  strategy reproduces the real race exactly; only the modelled difference carries uncertainty. A hypothetical SC/VSC is
  applied to both, i.e. it costs every car the same time.
- Positions: the anchored finish ranked against the rest of the field's real finishing times.

**Optimiser**: every 1–3-stop plan on new tyres with stints ≥ 5 laps and ≥ 2 reliable dry compounds. It is scored in
closed form; the best 10 distinct plans (same multiset of stints = same plan) are then Monte Carlo'd.

**Validation (backtest of every driver's real strategy, no anchoring, all 2024 dry races)**: median |error| 0.71 s
per driver over ~95-minute races; 90% within 5 s. On races without SC/VSC/red: median 0.36 s, 95% within 5 s.
Worst: Australia (8 s median) and Qatar (5 s), where SC bunching and late incidents aren't modelled.

## 9. Strategy simulator Stage B: traffic and overtaking

Code: `analysis/traffic_sim.py`. It is on by default in the UI and can be switched off for the clean-air (Stage A) figure.

- **Field**: every car not being simulated keeps its real crossing times (lead-lap finishers only).
- **Free laps**: the simulated driver's free lap = real lap + (Stage A plan − Stage A real strategy) per lap, on the
  same draws. The real plan therefore replays the real race exactly.
- **Interaction**: when the what-if brings the driver from behind a car at the end of lap L−1 to ahead of it by the
  end of lap L, and that pass didn't happen in reality at that lap, an overtaking trial runs.
  - Under SC/VSC/red: no pass.
  - Either car pitting that lap: the place change happens through the pits, no trial.
  - Otherwise: a pass with probability P(advantage).
  - A failed pass holds the driver 0.3 s behind that car (ASSUMPTION); a pass costs 0.2 s (ASSUMPTION).
- **Overtaking curve, fitted per race**: every lap a car started within 1 s of another on the same lap (no pits, not
  neutralised) gives one battle. Advantage = model free-air lap time of the car ahead − the car behind (on their real
  tyres); outcome = pass by the next line. Logistic regression with a weak Gaussian prior (logit intercept −2.5 ± 1.5,
  slope 2.0 ± 1.5 per s/lap). MAP fit; a Laplace covariance gives the per-draw curve uncertainty.
  - **Advantage needed for a 50% pass (2024)**: Bahrain 0.7 s, Monza / Spa / Las Vegas ≈ 1.0 s, Hungary 1.2 s,
    Singapore 1.7 s, Monaco 2.5 s (3 passes in 364 battles). The ordering matches each circuit's reputation.
- **Hypothetical SC**: at the end of each SC block the lead-lap field (and the simulated drivers) close up to 0.6 s
  gaps (ASSUMPTION); no passing during it.
- **Optimiser**: exhaustive clean-air ranking first, then the shortlist is re-run with traffic and re-ranked.
- **Example, Hungary 2025, Piastri alternatives (Norris on his real strategy)**:

  | Plan | Clean air | With traffic | P(PIA ahead of NOR), with traffic |
  |---|---|---|---|
  | Real two-stop | 0.0 s | 0.0 s (exact replay) | 0% |
  | Norris's one-stop (L31) | −0.4 s | +2.2 s | 26% |
  | One-stop at L35 | −2.7 s | −0.9 s | 82% |
  | Clean-air optimiser pick M25-H20-M25 | −7.0 s | −0.5 s (held ~5 laps) | 47% |

  Traffic turns the clean-air favourite into a coin flip, which is the track-position effect Hungary is known for.
