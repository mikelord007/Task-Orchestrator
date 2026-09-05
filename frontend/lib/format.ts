/** Formatting rules. A missing number is a dash, never a zero. */

export const DASH = "—";

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return `${(value * 100).toFixed(digits)}`;
}

export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(3)}`;
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`;
  return `${Math.round(value)}ms`;
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return value.toFixed(digits);
}

export function compactTokens(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

/** 2026-09-06T09:34:00Z -> 09-06 09:34 */
export function shortTs(iso: string | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

/** Signed delta, for before -> after readouts. */
export function delta(before: number | null, after: number | null, scale = 100, digits = 1): string {
  if (before === null || after === null) return DASH;
  const d = (after - before) * scale;
  const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
  return `${sign}${Math.abs(d).toFixed(digits)}`;
}
