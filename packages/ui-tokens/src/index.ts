/** Same values as tokens.css, for React Native (which has no CSS variables). */
export const light = {
  bg: "#f8fafc", panel: "#ffffff", panel2: "#f8fafc", line: "#e2e8f0",
  ink: "#0f172a", ink2: "#475569", ink3: "#64748b",
  rail: "#ffffff", railInk: "#475569",
  acc: "#4f46e5", accInk: "#ffffff", accSoft: "#eef2ff", accText: "#4338ca",
  good: "#059669", goodSoft: "#ecfdf5", goodText: "#047857",
  warn: "#d97706", warnSoft: "#fffbeb", warnText: "#b45309",
  bad: "#dc2626", badSoft: "#fef2f2", badText: "#b91c1c",
} as const;

export const dark: Record<keyof typeof light, string> = {
  bg: "#0b1120", panel: "#111827", panel2: "#0f172a", line: "#1f2a3d",
  ink: "#e2e8f0", ink2: "#a5b1c4", ink3: "#7c8aa0",
  rail: "#0f172a", railInk: "#a5b1c4",
  acc: "#818cf8", accInk: "#0b1020", accSoft: "#1e1b4b", accText: "#a5b4fc",
  good: "#34d399", goodSoft: "#052e22", goodText: "#6ee7b7",
  warn: "#fbbf24", warnSoft: "#2d1f05", warnText: "#fcd34d",
  bad: "#f87171", badSoft: "#3a1414", badText: "#fca5a5",
};

export const radius = { sm: 6, md: 8, lg: 12 } as const;
export const fonts = { ui: "Plus Jakarta Sans", num: "JetBrains Mono" } as const;
