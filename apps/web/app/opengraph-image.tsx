import { ImageResponse } from "next/og";

// The preview card when the home page is shared (WhatsApp, LinkedIn, X). Built once at build time.
export const alt = "BrewMyJob: your job alerts, brewed into applications worth sending";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between",
        background: "#FBF7F1", color: "#1E1712", padding: 72, fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 40, fontWeight: 800, letterSpacing: -1 }}>
          <svg width="56" height="56" viewBox="0 0 32 32" fill="none" stroke="#1E1712" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12h18v8a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7z" /><path d="M23 14h2.5a3.5 3.5 0 0 1 0 7H23" />
            <path d="M10 4c0 2 2 2 2 4M15 4c0 2 2 2 2 4" />
          </svg>
          brewmyjob
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 76, fontWeight: 800, lineHeight: 1.02, letterSpacing: -3 }}>
          <span>Your job alerts, brewed into</span>
          <span style={{ display: "flex" }}>
            applications&nbsp;<span style={{ background: "#F5A524", padding: "0 12px", borderRadius: 10 }}>worth sending.</span>
          </span>
        </div>
        <div style={{ display: "flex", fontSize: 28, color: "#4A3B2F" }}>
          LinkedIn + Naukri alerts · match scores · your best resume · you click Apply
        </div>
      </div>
    ),
    size,
  );
}
