import { useState } from "react";
import { useMantineColorScheme } from "@mantine/core";
import { SCREENS, useAppState } from "../state.jsx";

// Dev-only chrome, not part of the eventual product UI.
export default function DevSwitcher() {
  const { screen, goto } = useAppState();
  const [collapsed, setCollapsed] = useState(true);
  const { setColorScheme } = useMantineColorScheme();

  return (
    <div className="pp-dev-switcher">
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", cursor: "pointer", fontSize: 10, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--pp-ink-faint)", background: "var(--pp-leaf-raised)", border: "1px solid var(--pp-rule)", borderRadius: collapsed ? 6 : "6px 6px 0 0", boxShadow: "var(--pp-shadow-card)" }}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span>prototype states</span>
        <span>{collapsed ? "▸" : "▾"}</span>
      </div>
      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 10, maxWidth: 280, background: "var(--pp-leaf-raised)", border: "1px solid var(--pp-rule)", borderTop: "none", borderRadius: "0 0 6px 6px", boxShadow: "var(--pp-shadow-card)" }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {SCREENS.map((s, i) => (
              <button
                key={s}
                className="pp-dev-btn"
                data-on={screen === s}
                onClick={() => goto(s)}
              >
                {i + 1} · {s}
              </button>
            ))}
            <button className="pp-dev-btn" onClick={() => setColorScheme("light")}>◐ light</button>
            <button className="pp-dev-btn" onClick={() => setColorScheme("dark")}>◐ dark</button>
            <button className="pp-dev-btn" onClick={() => setColorScheme("auto")}>◐ auto</button>
          </div>
        </div>
      )}
    </div>
  );
}
