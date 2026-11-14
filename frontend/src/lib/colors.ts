// Colour roles. Driver A/B validated with the dataviz validator on the dark surface #1a1a19
// (CVD ΔE 26.8, normal-vision ΔE 31.8). Colour follows the A/B slot, never team colour:
// teammates share a team colour.

export const DRIVER = { a: "#3987e5", b: "#d95926" } as const;

// Sequential blue ramp, slow (dark, recedes into the surface) → fast (light).
export const SPEED_RAMP = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5",
  "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"];

// Driver inputs: braking / partial-or-coasting / full throttle. Deliberately not the A/B hues.
export const INPUTS = { brake: "#e66767", partial: "#8a8984", full: "#199e70" } as const;

// Pirelli's conventional compound colours, always shown alongside the compound name.
export const COMPOUND: Record<string, string> = {
  SOFT: "#e10600",
  MEDIUM: "#ffd12e",
  HARD: "#f0f0ec",
  INTERMEDIATE: "#39b54a",
  WET: "#0067ad",
};

export function speedColor(v: number, min: number, max: number): string {
  const t = Math.max(0, Math.min(1, (v - min) / Math.max(1, max - min)));
  return SPEED_RAMP[Math.round(t * (SPEED_RAMP.length - 1))];
}

// Ordinal ramps for multi-lap overlays: one hue per driver, darker = earlier (lower tyre age), lighter = later.
// Validated with the dataviz validator (--ordinal --mode dark): monotone L, visible steps, ≥ 3:1 at the dark end.
export const LAP_RAMP = {
  a: ["#2a78d6", "#5598e7", "#86b6ef", "#b7d3f6"],
  b: ["#c94a11", "#e96a3a", "#f69573", "#ffbfa9"],
} as const;
