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
  session_type: "Race" | "Qualifying";
  date_start: string | null;
  date_end: string | null;
  available: boolean;
  capabilities: Capabilities;
};

export type Season = { year: number; source: string };

export type GPEvent = {
  meeting_key: string | number;
  meeting_name: string;
  country: string;
  location: string;
  round: number;
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
  raw_trend: Fit | null;
  fuel_corrected_trend: Fit | null;
  sector_trends: Partial<Record<"s1_s" | "s2_s" | "s3_s", Fit | null>>;
};
export type Degradation = { ci_level: number; fuel_s_per_lap: number; stints: StintTrend[]; laps: Lap[] };

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

export const api = {
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
  compare: (id: string, params: Record<string, string | number | undefined | null>) =>
    get<CompareResult>(`/api/sessions/${id}/compare`, params),
};
