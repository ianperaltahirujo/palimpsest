import { useEffect, useState } from "react";
import { Anchor, Box, PasswordInput, Radio, Text } from "@mantine/core";
import { VENDOR_COLORS } from "../theme.js";
import { BACKEND_COPY } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import * as api from "../api.js";

const ENV_VAR = { anthropic: "ANTHROPIC_API_KEY", gemini: "GEMINI_API_KEY" };
const HEALTH_KEY = { anthropic: "anthropic_key_present", gemini: "gemini_key_present" };

// Part B of the pass-3 plan: vendor colour lives on the selection
// indicator, not a separate dot. Radio.Card gives the radio semantics and
// keyboard nav; the indicator itself is a plain styled div rather than
// Mantine's Radio.Indicator, because the spec calls for a circle that's
// WHITE by default and only takes the vendor's colour (a gradient, for
// Gemini -- Mantine's `color` prop can't express that) once checked --
// Radio.Indicator's own checked/unchecked states don't map onto that.
//
// Containment rule: vendor hues (Gemini's blue-purple, Claude's orange,
// Google's blue) appear ONLY on this control's indicator fill and its
// left bar. The Registration system uses blue/magenta SEMANTICALLY
// (translated layer vs. original) everywhere else in the app, and a
// leaked vendor hue would corrupt that language.
export default function BackendSelector() {
  const t = useT();
  const { selectedBackend, setSelectedBackend } = useAppState();

  // MOCK mode keeps its own local state and the fake key-check flow
  // exactly as before. Real mode reads/writes the shared selectedBackend
  // (state.jsx) so Estimate's "Translate" button submits the same
  // backend this control shows selected.
  const [mockBackend, setMockBackend] = useState("gemini");
  const [apiKey, setApiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState("idle"); // idle | checking | ok | empty
  const [health, setHealth] = useState(null);

  const backend = MOCK ? mockBackend : selectedBackend || "gemini";
  const copy = BACKEND_COPY[backend];

  useEffect(() => {
    if (MOCK) return;
    api.health().then(setHealth).catch(() => {});
  }, []);

  function selectBackend(v) {
    if (MOCK) {
      setMockBackend(v);
      setKeyStatus("idle");
    } else {
      setSelectedBackend(v);
    }
  }

  function checkKey() {
    if (!apiKey.trim()) {
      setKeyStatus("empty");
      return;
    }
    setKeyStatus("checking");
    setTimeout(() => setKeyStatus("ok"), 650);
  }

  const keyPresent = health?.[HEALTH_KEY[backend]];

  return (
    <div>
      <Radio.Group value={backend} onChange={selectBackend}>
        <Box style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {Object.keys(BACKEND_COPY).map((id) => {
            const checked = backend === id;
            return (
              <Radio.Card
                key={id}
                value={id}
                data-backend={id}
                // Selection reads ONLY from the left bar + filled
                // indicator below -- no card-level border/wash. The
                // Registration system uses --pp-register as a semantic
                // colour (the translated layer) elsewhere in the app, and
                // reusing it here as a generic "selected" highlight would
                // blur that meaning for no reason -- the vendor's own
                // colour on the indicator already says "this one".
                style={{ position: "relative", padding: "8px 9px 8px 13px", border: "1px solid transparent", background: "transparent" }}
              >
                <span className={"pp-backend-bar" + (checked ? " active" : "")} style={{ background: VENDOR_COLORS[id] }} />
                {/* Grid, not Group -- the indicator must centre on the
                    TITLE ROW only (row 1), not the two-line card as a
                    whole, which is what a flex `align="center"` would do
                    once the sub-line is present. */}
                <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", columnGap: 9, rowGap: 1 }}>
                  <span
                    className={"pp-backend-indicator" + (checked ? " checked" : "")}
                    style={{ gridRow: 1, gridColumn: 1, alignSelf: "center", ...(checked ? { background: VENDOR_COLORS[id] } : {}) }}
                    aria-hidden="true"
                  />
                  <Text size="sm" fw={600} style={{ gridRow: 1, gridColumn: 2, alignSelf: "center" }}>
                    {BACKEND_COPY[id].label}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ gridRow: 2, gridColumn: 2 }}>
                    {t(`backend.sub.${id}`)}
                  </Text>
                </div>
              </Radio.Card>
            );
          })}
        </Box>
      </Radio.Group>

      {copy.needsKey && MOCK && (
        <div style={{ marginTop: 10 }}>
          <PasswordInput
            label={t("backend.apiKeyLabel")}
            placeholder="AIza..."
            size="sm"
            value={apiKey}
            onChange={(e) => setApiKey(e.currentTarget.value)}
            rightSectionWidth={64}
            rightSection={
              <button className="pp-btn-mini" onClick={checkKey} style={{ marginRight: 4 }}>
                {t("backend.check")}
              </button>
            }
          />
          <Text size="xs" mt={7} c={keyStatus === "ok" ? "ok" : keyStatus === "empty" ? "flag" : "dimmed"}>
            {t(`backend.status.${keyStatus}`)}
          </Text>
          <Text size="xs" c="dimmed" mt={6}>
            {t("backend.keyNote")}{" "}
            <Anchor href="https://aistudio.google.com/apikey" target="_blank" rel="noopener" size="xs">
              {t("backend.getKey")}
            </Anchor>
          </Text>
        </div>
      )}

      {copy.needsKey && !MOCK && (
        <div style={{ marginTop: 10 }}>
          <Text size="xs" c="dimmed" ff="monospace" mb={4}>
            {ENV_VAR[backend]}
          </Text>
          <Text size="xs" fw={600} c={keyPresent ? "ok" : "flag"}>
            {keyPresent ? t("backend.keyDetected") : t("backend.keyMissing")}
          </Text>
          <Text size="xs" c="dimmed" mt={6}>
            {t("backend.keyServerNote")}
          </Text>
        </div>
      )}
    </div>
  );
}
