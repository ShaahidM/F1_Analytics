import { create } from "zustand";
import type { CompareMode } from "./api";

export type ColorBy = "driver" | "speed" | "inputs" | "faster";

export type ModeParams = {
  lap?: number;
  tyre_age?: number;
  compound_a?: string;
  compound_b?: string;
  lap_a?: number;
  lap_b?: number;
};

type State = {
  year: number | null;
  sessionId: string | null;
  driverA: number | null;
  driverB: number | null;
  mode: CompareMode;
  params: ModeParams;
  /** Shared cursor: track distance in metres. Links the map and every chart. */
  cursorS: number | null;
  /** Shared distance window [from, to] in metres; null = full lap. */
  xRange: [number, number] | null;
  colorBy: ColorBy;
  setYear: (y: number | null) => void;
  setSession: (id: string | null) => void;
  setDrivers: (a: number | null, b: number | null) => void;
  setMode: (m: CompareMode) => void;
  setParams: (p: Partial<ModeParams>) => void;
  setCursorS: (s: number | null) => void;
  setXRange: (r: [number, number] | null) => void;
  setColorBy: (c: ColorBy) => void;
};

export const useStore = create<State>((set) => ({
  year: null,
  sessionId: null,
  driverA: null,
  driverB: null,
  mode: "fastest",
  params: {},
  cursorS: null,
  xRange: null,
  colorBy: "driver",
  setYear: (year) => set({ year, sessionId: null, driverA: null, driverB: null, params: {}, xRange: null }),
  setSession: (sessionId) => set({ sessionId, driverA: null, driverB: null, params: {}, xRange: null }),
  setDrivers: (driverA, driverB) => set({ driverA, driverB, params: {} }),
  setMode: (mode) => set({ mode }),
  setParams: (p) => set((s) => ({ params: { ...s.params, ...p } })),
  setCursorS: (cursorS) => set({ cursorS }),
  setXRange: (xRange) => set({ xRange }),
  setColorBy: (colorBy) => set({ colorBy }),
}));
