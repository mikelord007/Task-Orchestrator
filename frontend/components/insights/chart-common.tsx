export const CHART_COLORS = {
  train: "#f3f2f2",
  holdout: "#9b9797",
  pass: "#f3f2f2",
  fail: "#ff563c",
  drift: "#ff563c",
  mute: "#7d7979",
  grid: "#2d2b2b",
  line: "#605d5d",
};

/** Shared dark-theme styling for Recharts tooltips. */
export const tooltipStyle = {
  contentStyle: {
    background: "#232120",
    border: "1px solid #605d5d",
    borderRadius: 0,
    fontFamily: "var(--font-jetbrains-mono), monospace",
    fontSize: 13,
    color: "#f3f2f2",
  },
  labelStyle: { color: "#bab6b6" },
  itemStyle: { color: "#f3f2f2" },
};

export const axisTick = {
  fontFamily: "var(--font-jetbrains-mono), monospace",
  fontSize: 17,
  fill: "#7d7979",
};
