export const CHART_COLORS = {
  train: "#4cc2ff",
  holdout: "#a98bff",
  pass: "#3fd3a0",
  fail: "#f2616a",
  drift: "#e8b14a",
  mute: "#6d7d8d",
  grid: "#212c38",
};

/** Shared dark-theme styling for Recharts tooltips. */
export const tooltipStyle = {
  contentStyle: {
    background: "#0e141b",
    border: "1px solid #212c38",
    borderRadius: 3,
    fontSize: 11,
    color: "#d7e0e8",
  },
  labelStyle: { color: "#9aa9b8" },
  itemStyle: { color: "#d7e0e8" },
};

export const axisTick = { fontSize: 11, fill: "#6d7d8d" };
