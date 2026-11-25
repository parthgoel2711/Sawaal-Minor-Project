import type { Cell, QueryResult, Theme } from "../types";

export type ChartKind = "bar" | "line";

export interface ChartSpec {
  kind: ChartKind;
  xKey: string;
  /** Every numeric column that can be plotted. */
  measures: string[];
  /** The default series: the first measure plus any measures on a similar scale (one shared y-axis). */
  series: string[];
  data: Record<string, Cell>[];
  temporal: boolean;
  clipped: number; // how many rows were left out of the chart
}

const MAX_SERIES = 4;
const MAX_MEASURES = 8;
const SAME_SCALE_RATIO = 5;
const MAX_BARS = 50;
const MAX_POINTS = 500;
const DATE_LIKE = /^\d{4}(-\d{2}(-\d{2})?)?([ T].*)?$/;
const ID_COLUMN = /(^id$|_id$)/i;

/**
 * Pick a sensible chart for a query result: one label column on the x-axis and up to
 * four numeric columns as series. Dates/months/years become a line chart, anything else a bar chart.
 * Returns null when the result has nothing to plot.
 */
export function inferChart(result: QueryResult): ChartSpec | null {
  const { columns, column_types: types, rows } = result;
  if (rows.length < 2 || columns.length < 2) return null;

  const numeric = types.map((t, i) => (t === "number" ? i : -1)).filter((i) => i >= 0);
  let xIdx = types.findIndex((t) => t === "text");
  if (xIdx === -1) {
    // e.g. SELECT year, revenue ... -> use the first numeric column as the label
    if (numeric.length < 2) return null;
    xIdx = numeric[0];
  }
  const yIdx = numeric.filter((i) => i !== xIdx && !ID_COLUMN.test(columns[i])).slice(0, MAX_MEASURES);
  if (yIdx.length === 0) return null;

  const xValues = rows.map((r) => r[xIdx]);
  const temporal =
    xValues.every((v) => typeof v === "string" && DATE_LIKE.test(v)) ||
    (types[xIdx] === "number" && xValues.every((v) => typeof v === "number" && Number.isInteger(v) && v >= 1900 && v <= 2100));

  const kind: ChartKind = temporal && rows.length > 2 ? "line" : "bar";
  const xKey = columns[xIdx];
  let data = rows.map((r) => {
    const point: Record<string, Cell> = { [xKey]: r[xIdx] === null ? "(empty)" : r[xIdx] };
    for (const i of yIdx) point[columns[i]] = r[i];
    return point;
  });
  if (temporal) data = [...data].sort((a, b) => String(a[xKey]).localeCompare(String(b[xKey]), undefined, { numeric: true }));

  const limit = kind === "bar" ? MAX_BARS : MAX_POINTS;
  const clipped = Math.max(0, data.length - limit);
  const measures = yIdx.map((i) => columns[i]);
  return { kind, xKey, measures, series: sameScaleGroup(measures, data), data: data.slice(0, limit), temporal, clipped };
}

/**
 * Measures that can share one y-axis with the first measure (largest values within 5x of each other).
 * A rating (0-5) and a count (0-120) are never drawn on the same axis; the user picks one instead.
 */
export function sameScaleGroup(measures: string[], data: Record<string, Cell>[]): string[] {
  const peak = (m: string) => Math.max(0, ...data.map((d) => Math.abs(typeof d[m] === "number" ? (d[m] as number) : 0)));
  const base = peak(measures[0]);
  const group = measures.filter((m, i) => {
    if (i === 0) return true;
    const p = peak(m);
    if (base === 0 || p === 0) return false;
    return Math.max(p, base) / Math.min(p, base) <= SAME_SCALE_RATIO;
  });
  return group.slice(0, MAX_SERIES);
}

/**
 * Chart colours: the validated categorical palette, stepped separately for each theme,
 * assigned to series in fixed order.
 */
export const CHART_COLORS: Record<Theme, {
  series: string[]; grid: string; axis: string; muted: string; surface: string; ink: string; hover: string;
}> = {
  light: {
    series: ["#2851c4", "#b8862b", "#2f7d55", "#8a8c94"],
    grid: "#e6e6e2",
    axis: "#cfcfca",
    muted: "#6e7079",
    surface: "#ffffff",
    ink: "#1d1e22",
    hover: "rgba(29, 30, 34, 0.05)",
  },
  dark: {
    series: ["#8aa6f5", "#d9a54c", "#5fb98a", "#a0a2aa"],
    grid: "#2b2c31",
    axis: "#3a3b41",
    muted: "#8a8c94",
    surface: "#1b1c1f",
    ink: "#ececea",
    hover: "rgba(255, 255, 255, 0.06)",
  },
};
