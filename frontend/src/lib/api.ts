// Typed client for the FastAPI backend (see backend/app/api/routes.py).

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type Capabilities = {
  lap_times: boolean;
  sectors: boolean;
  compounds: boolean;
  pit: boolean;
  telemetry: boolean;
  position: boolean;
  weather: boolean;
  race_control: boolean;
  intervals: boolean;
  notes: string[];
};

export type SessionRef = {
  id: string;
  source: string;
  year: number;
  round: number | null;
  meeting_name: string;
  country: string;
  location: string;
  circuit_key: number | null;
  circuit_name: string;
  session_name: string;
  session_type: "Race" | "Qualifying" | "Practice";
  date_start: string | null;
  date_end: string | null;
  available: boolean;
  capabilities: Capabilities;
};

export type Season = { year: number; source: string; limited: boolean };

export type GPEvent = {
  meeting_key: string | number;
  meeting_name: string;
  country: string;
  location: string;
  round: number | null;
  date_start: string | null;
  sessions: SessionRef[];
};

export type Driver = {
  driver_number: number;
  code: string;
  full_name: string;
  team: string;
  team_colour: string | null;
};

export type SessionDetail = SessionRef & { drivers: Driver[] };

export type Lap = {
  driver_number: number;
  lap_number: number;
  lap_start: string | null;
  lap_time_s: number | null;
  s1_s: number | null;
  s2_s: number | null;
  s3_s: number | null;
  i1_speed: number | null;
  i2_speed: number | null;
  st_speed: number | null;
  is_pit_out: boolean;
  is_pit_in: boolean;
  stint: number | null;
  compound: string | null;
  tyre_age: number | null;
  sc: boolean;
  vsc: boolean;
  red: boolean;
  yellow: boolean;
  deleted: boolean;
  min_interval_s: number | null;
  clean: boolean;
  exclude_reasons: string[];
  flags: string[];
  tyre_age_assumed: boolean;
};

export type CompareMode = "fastest" | "same_lap" | "same_tyre_age" | "custom";

export type CompareResult = {
  mode: CompareMode;
  a: Lap;
  b: Lap;
  differences: { kind: string; message: string }[];
  equivalent: boolean;
};

export type Corner = {
  number: number;
  letter: string;
  angle: number | null;
  x: number;
  y: number;
  s: number;
  source: string;
};

export type Track = {
  reference: {
    driver_number: number;
    lap_number: number;
    lap_time_s: number;
    length_m: number;
    s: number[];
    x: number[];
    y: number[];
  };
  corners: Corner[];
  zones: Zone[];
  rotation: number;
  pit_loss_s: number | null;
  units_per_m: number;
  notes: string[];
};

export type Zone = {
  id: number;
  label: string;
  corners: string[];
  kind: "braking" | "flat";
  start_s: number;
  apex_s: number;
  end_s: number;
};

export type Tier = "M" | "C" | "E" | "I" | "A";
export type MetricDef = { unit: string; tier: Tier; note: string };
export type ZoneMetrics = { zone_id: number } & Partial<Record<string, number | null>>;
export type CornerResult = {
  driver_number: number;
  lap_number: number;
  metrics: ZoneMetrics[];
  definitions: Record<string, MetricDef>;
};

export type Fit = { slope: number; ci_low: number; ci_high: number; intercept: number; residual_sd: number; n: number };
export type StintTrend = {
  driver_number: number;
  stint: number;
  compound: string | null;
  lap_start: number;
  lap_end: number;
  tyre_age_start: number | null;
  tyre_age_assumed: boolean;
  n_laps: number;
  n_used: number;
  median_lap_s: number | null;
  code?: string | null;
  team?: string | null;
  raw_trend: Fit | null;
  fuel_corrected_trend: Fit | null;
  sector_trends: Partial<Record<"s1_s" | "s2_s" | "s3_s", Fit | null>>;
};
export type Degradation = { ci_level: number; fuel_s_per_lap: number; stints: StintTrend[]; laps: Lap[] };

export type StyleRow = {
  lap_number: number;
  stint: number | null;
  compound: string | null;
  tyre_age: number | null;
  lap_time_s: number;
} & Record<string, number | null>;
export type StyleResult = { definitions: Record<string, MetricDef>; drivers: Record<string, StyleRow[]> };

export type Pattern =
  | "consistent_with_management"
  | "consistent_with_grip_loss"
  | "mixed"
  | "no_clear_pattern"
  | "insufficient_data";
export type ZoneTrend = {
  stint: number;
  zone_id: number;
  compound: string | null;
  n_laps: number;
  tyre_age_span: number;
  trends: Record<string, Fit | null>;
  significant: Record<string, -1 | 0 | 1>;
  pattern: Pattern;
  evidence: string[];
};
export type PreservationDriver = {
  driver_number: number;
  zone_trends: ZoneTrend[];
  lap_trends: { stint: number; compound: string | null; n_laps: number; trends: Record<string, Fit | null> }[];
  rows: ({ lap_number: number; stint: number; compound: string | null; tyre_age: number; zone_id: number } & Record<string, number | null>)[];
};
export type PreservationResult = {
  indicators: Record<string, { label: string; unit: string; increase_means: string; min_change: number | null }>;
  style_metrics: Record<string, MetricDef>;
  confounders: string[];
  zones: Zone[];
  drivers: Record<string, PreservationDriver>;
};

export type Coef = { estimate: number; ci_low: number; ci_high: number };
export type ModelB =
  | { ok: false; reason: string }
  | {
      ok: true;
      ci_level: number;
      n_laps: number;
      n_drivers: number;
      r2: number;
      residual_sd: number;
      lap_effect: Coef;
      track_temp_effect: Coef | null;
      field_tyre_slopes: Record<string, Coef>;
      compound_offsets: Record<string, Coef>;
      reference: { compound: string; lap_number: number; track_temp: number | null };
      pace_curves: {
        tag: "A" | "B";
        driver_number: number;
        compound: string;
        tyre_age: number[];
        lap_time: number[];
        ci_low: number[];
        ci_high: number[];
        driver_used_ages: [number, number] | null;
      }[];
      driver_tyre_slopes: Record<"A" | "B", { driver_number: number; compounds: Record<string, Coef & { n_laps: number }> }>;
      warnings: string[];
      assumptions: string[];
    };

export type PitStop = {
  lap: number;
  from_compound: string | null;
  to_compound: string | null;
  from_tyre_age: number | null;
  lane_s: number | null;
  stationary_s: number | null;
  in_lap_s: number | null;
  out_lap_s: number | null;
  baseline_lap_s: number | null;
  estimated_loss_s: number | null;
  under_neutralisation: boolean;
};
export type PitCycle = {
  first_stopper: number;
  second_stopper: number;
  first_lap: number;
  second_lap: number;
  gap_before_s: number | null;
  gap_after_s: number | null;
  net_change_s: number | null;
  lane_time_diff_s: number | null;
  on_track_diff_s: number | null;
  compounds: { first_to: string | null; second_from: string | null; second_to: string | null };
  neutralised: boolean;
  outcome: string;
};
export type Strategy = {
  order: number[];
  total_laps: number;
  stints: { driver_number: number; stint: number; compound: string | null; lap_start: number; lap_end: number;
    tyre_age_start: number | null; tyre_age_assumed: boolean }[];
  pit_stops: Record<string, PitStop[]>;
  pit_loss_reference: Record<string, number> | null;
  gap: { lap: number; gap_s: number }[];
  positions: Record<string, { lap: number; position: number }[]>;
  cycles: PitCycle[];
  offset: {
    stops: { a: number; b: number };
    stop_laps: { a: number[]; b: number[] };
    gap_before_first_stop_s: number | null;
    gap_after_last_stop_s: number | null;
    gap_at_finish_s: number | null;
    net_change_s: number | null;
    pit_loss_s: { a: number; b: number };
  } | null;
  timing_basis: string;
};

export type LineStats = { mean: number; sd: number; n: number; se: number };
export type LineResult = {
  zones: Zone[];
  rows: { zone_id: number; a: LineStats | null; b: LineStats | null; diff_m: number | null; se_m: number | null; z: number | null;
    halves: number[] | null; replicated: boolean; significant: boolean }[];
};

export type SeasonDriver = { code: string; full_name: string; teams: string[]; races: number; team_colour: string | null };
type CoefWithN = Coef & { n_laps?: number };
export type RaceSummary = {
  session_id: string;
  round: number | null;
  meeting_name: string;
  location?: string;
  date?: string | null;
  status: "ok" | "absent" | "error";
  message?: string;
  a_number?: number;
  b_number?: number;
  conditions?: "dry" | "mixed" | "wet" | "unknown";
  finish?: { a: number | null; b: number | null };
  stops?: { a: number; b: number };
  pace_gap?: { median_s: number; ci_low: number; ci_high: number; n_laps: number } | null;
  clean_laps?: { a: number; b: number };
  model?: { lap_effect: Coef; field: Record<string, Coef>; a: Record<string, CoefWithN>; b: Record<string, CoefWithN>; warnings: string[] } | null;
  style?: Partial<Record<"a" | "b", Record<string, number | null>>>;
  patterns?: Partial<Record<"a" | "b", Record<string, number>>>;
  line?: { significant: { zone: string; diff_m: number }[]; n_zones: number } | null;
};
export type SeasonAggregate = { driver: string; metric: string; median: number; mean: number; races: number };
export type SeasonResult = {
  state: "running" | "done" | "failed" | "not_started";
  done?: number;
  total?: number;
  current?: string | null;
  error?: string;
  races: RaceSummary[];
  aggregate: SeasonAggregate[];
};

export type SimStint = { compound: string; laps: number; start_age: number };
export type Interval = { median: number; low: number; high: number };
export type WhatIfModel = {
  total_laps: number;
  model: {
    n_laps: number;
    r2: number;
    residual_sd: number;
    fuel_track_per_lap: { estimate: number; se: number };
    compounds: Record<string, { offset: number; slope: number; slope_se: number; quadratic: boolean; oldest_tyre: number; unreliable: string | null }>;
  };
  backtest: { errors_s: Record<string, number>; median_abs_error_s: number | null; n_drivers: number };
  pit_loss: { by_driver: Record<string, number>; field_median: number; spread_sd: number; multiviewer: Record<string, number> | null };
  actual: Record<string, SimStint[]>;
  neutralised_laps: number[];
  assumptions: string[];
};
export type SimDriver = {
  code: string;
  stints: SimStint[];
  delta_vs_actual_strategy: Interval;
  laps: number[];
  warnings: string[];
  extrapolation: string[];
  position: { median: number; distribution: Record<string, number>; actual: number };
};
export type SimResult = {
  drivers: Record<string, SimDriver>;
  assumptions: string[];
  p_first_ahead?: number;
  gap_by_lap?: { median: number[]; low: number[]; high: number[]; actual: number[] };
};
export type OptResult = {
  driver: number;
  code: string;
  max_stops: number;
  actual: SimStint[];
  plans: { stints: SimStint[]; stops: number; delta_vs_actual_strategy: Interval; extrapolation: string[] }[];
};
export type ScenarioIn = { sc: number[]; vsc: number[] };

type Num = number | null;

export type Trace = {
  driver_number: number;
  lap_number: number;
  lap_time_s: number | null;
  grid_m: number;
  length_m: number;
  s: number[];
  t: Num[];
  speed: Num[];
  throttle: Num[];
  brake: Num[];
  gear: Num[];
  rpm: Num[];
  drs: Num[];
  x: Num[];
  y: Num[];
  lateral_m: Num[];
  accel_g: Num[];
  sample_spacing_m: Num[];
  quality: {
    car_samples: number;
    pos_samples: number;
    max_pos_gap_s: number | null;
    has_gaps: boolean;
    trace_time_s: number;
  };
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function get<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const url = new URL(path, API_BASE);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(new URL(path, API_BASE), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  whatifModel: (id: string) => get<WhatIfModel>(`/api/sessions/${id}/whatif/model`),
  simulate: (id: string, drivers: { driver: number; stints: SimStint[] }[], scenario: ScenarioIn) =>
    post<SimResult>(`/api/sessions/${id}/whatif/simulate`, { drivers, scenario }),
  optimise: (id: string, driver: number, maxStops: number, scenario: ScenarioIn) =>
    post<OptResult>(`/api/sessions/${id}/whatif/optimise`, { driver, max_stops: maxStops, scenario }),
  seasons: () => get<Season[]>("/api/seasons"),
  events: (year: number) => get<GPEvent[]>(`/api/seasons/${year}/events`),
  session: (id: string) => get<SessionDetail>(`/api/sessions/${id}`),
  laps: (id: string, drivers: number[]) => get<Lap[]>(`/api/sessions/${id}/laps`, { drivers: drivers.join(",") }),
  track: (id: string) => get<Track>(`/api/sessions/${id}/track`),
  trace: (id: string, driver: number, lap: number) =>
    get<Trace>(`/api/sessions/${id}/trace`, { driver, lap, raw: "false" }),
  corners: (id: string, driver: number, lap: number) => get<CornerResult>(`/api/sessions/${id}/corners`, { driver, lap }),
  degradation: (id: string, drivers: number[], includeFlagged: boolean, fuel: number) =>
    get<Degradation>(`/api/sessions/${id}/degradation`, {
      drivers: drivers.join(","),
      include_flagged: String(includeFlagged),
      fuel_s_per_lap: fuel,
    }),
  style: (id: string, drivers: number[], includeFlagged: boolean) =>
    get<StyleResult>(`/api/sessions/${id}/style`, { drivers: drivers.join(","), include_flagged: String(includeFlagged) }),
  preservation: (id: string, drivers: number[], includeFlagged: boolean) =>
    get<PreservationResult>(`/api/sessions/${id}/preservation`, { drivers: drivers.join(","), include_flagged: String(includeFlagged) }),
  model: (id: string, drivers: number[], includeFlagged: boolean) =>
    get<ModelB>(`/api/sessions/${id}/model`, { drivers: drivers.join(","), include_flagged: String(includeFlagged) }),
  strategy: (id: string, drivers: number[]) => get<Strategy>(`/api/sessions/${id}/strategy`, { drivers: drivers.join(",") }),
  traffic: (id: string) => get<{ state: string; done: number; total: number }>(`/api/sessions/${id}/traffic`),
  line: (id: string, drivers: number[], includeFlagged: boolean) =>
    get<LineResult>(`/api/sessions/${id}/line`, { drivers: drivers.join(","), include_flagged: String(includeFlagged) }),
  longRuns: (id: string, includeFlagged: boolean) =>
    get<{ ci_level: number; runs: StintTrend[] }>(`/api/sessions/${id}/longruns`, { include_flagged: String(includeFlagged) }),
  seasonDrivers: (year: number) => get<SeasonDriver[]>(`/api/seasons/${year}/drivers`),
  seasonCompare: (year: number, a: string, b: string, includeWet: boolean) =>
    get<SeasonResult>(`/api/seasons/${year}/compare`, { a, b, include_wet: String(includeWet) }),
  compare: (id: string, params: Record<string, string | number | undefined | null>) =>
    get<CompareResult>(`/api/sessions/${id}/compare`, params),
};
