import { useEffect, useState } from "react";
import { Anchor, Box, PasswordInput, Radio, Text, TextInput } from "@mantine/core";
import { VENDOR_COLORS } from "../theme.js";
import { BACKEND_COPY } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { T, useT } from "../i18n.jsx";
import { MOCK, getApiBase, setApiBase } from "../config.js";
import * as api from "../api.js";

const ENV_VAR = { anthropic: "ANTHROPIC_API_KEY", gemini: "GEMINI_API_KEY" };
const HEALTH_KEY = { anthropic: "anthropic_key_present", gemini: "gemini_key_present" };
const KEY_FIELD = { anthropic: "anthropic_api_key", gemini: "gemini_api_key" };

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
  const [healthError, setHealthError] = useState(null);
  const [addressOpen, setAddressOpen] = useState(false);
  const [addressDraft, setAddressDraft] = useState(() => getApiBase());
  const [entryOpen, setEntryOpen] = useState(false);
  const [entryKey, setEntryKey] = useState("");
  const [entryStatus, setEntryStatus] = useState("idle"); // idle | saving | error

  const backend = MOCK ? mockBackend : selectedBackend || "gemini";
  const copy = BACKEND_COPY[backend];

  // Three states, not two: a fetch failure (no /api proxy, server not
  // started, server restarting) must render distinctly from a reachable
  // server that genuinely reports the key absent -- otherwise "not set"
  // shows up for a problem that isn't about the key at all. Exposed as a
  // named function (not just a mount-time effect) so the "recheck" link
  // below can refetch after the user actually starts/restarts the server,
  // rather than requiring a full page reload.
  function fetchHealth() {
    if (MOCK) return;
    setHealthError(null);
    api.health().then(setHealth).catch((e) => setHealthError(e));
  }

  useEffect(fetchHealth, []);

  function saveAddress() {
    setApiBase(addressDraft.trim());
    setAddressDraft(getApiBase());
    setAddressOpen(false);
    fetchHealth();
  }

  function submitEntryKey() {
    const value = entryKey.trim();
    if (!value) return;
    setEntryStatus("saving");
    api.setKeys({ [KEY_FIELD[backend]]: value })
      .then((h) => {
        setHealth(h);
        setEntryKey("");
        setEntryStatus("idle");
        setEntryOpen(false);
      })
      .catch(() => setEntryStatus("error"));
  }

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

      {!MOCK && (
        <div style={{ marginTop: 10 }}>
          {addressOpen ? (
            <Box style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
              <TextInput
                size="xs"
                style={{ flex: 1 }}
                label={t("backend.serverAddress")}
                placeholder="http://127.0.0.1:8765"
                value={addressDraft}
                onChange={(e) => setAddressDraft(e.currentTarget.value)}
                onKeyDown={(e) => e.key === "Enter" && saveAddress()}
              />
              <button className="pp-btn-mini" onClick={saveAddress}>
                {t("backend.serverAddressSave")}
              </button>
            </Box>
          ) : (
            <Text size="xs" c="dimmed" ff="monospace">
              {t("backend.serverAddress")}: {getApiBase() || t("backend.serverAddressSameOrigin")}{" "}
              <Anchor size="xs" component="button" type="button" onClick={() => setAddressOpen(true)}>
                {t("backend.serverAddressChange")}
              </Anchor>
            </Text>
          )}
        </div>
      )}

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

      {copy.needsKey && !MOCK && healthError && (
        <div style={{ marginTop: 10 }}>
          <Text size="xs" fw={600} c="flag">
            <T k="backend.healthUnreachable" />
          </Text>
          <Text size="xs" mt={6}>
            <Anchor size="xs" component="button" type="button" onClick={fetchHealth}>
              {t("backend.recheck")}
            </Anchor>
          </Text>
        </div>
      )}

      {copy.needsKey && !MOCK && !healthError && health === null && (
        <div style={{ marginTop: 10 }}>
          <Text size="xs" c="dimmed">{t("backend.healthChecking")}</Text>
        </div>
      )}

      {copy.needsKey && !MOCK && !healthError && health !== null && keyPresent && !entryOpen && (
        <div style={{ marginTop: 10 }}>
          <Text size="xs" c="dimmed" ff="monospace" mb={4}>
            {ENV_VAR[backend]}
          </Text>
          <Text size="xs" fw={600} c="ok">
            {t("backend.keyDetected")}
          </Text>
          <Text size="xs" c="dimmed" mt={6}>
            {t("backend.keyServerNote")}{" "}
            <Anchor size="xs" component="button" type="button" onClick={() => setEntryOpen(true)}>
              {t("backend.keyChange")}
            </Anchor>
            {" · "}
            <Anchor size="xs" component="button" type="button" onClick={fetchHealth}>
              {t("backend.recheck")}
            </Anchor>
          </Text>
        </div>
      )}

      {copy.needsKey && !MOCK && !healthError && health !== null && (!keyPresent || entryOpen) && (
        <div style={{ marginTop: 10 }}>
          <PasswordInput
            label={t("backend.apiKeyLabel")}
            placeholder={backend === "anthropic" ? "sk-ant-..." : "AIza..."}
            size="sm"
            value={entryKey}
            onChange={(e) => { setEntryKey(e.currentTarget.value); setEntryStatus("idle"); }}
            onKeyDown={(e) => e.key === "Enter" && submitEntryKey()}
            rightSectionWidth={64}
            rightSection={
              <button className="pp-btn-mini" onClick={submitEntryKey} style={{ marginRight: 4 }}>
                {entryStatus === "saving" ? t("backend.keyEntrySaving") : t("backend.keyEntrySave")}
              </button>
            }
          />
          <Text size="xs" mt={7} c={entryStatus === "error" ? "flag" : "dimmed"}>
            {entryStatus === "error"
              ? t("backend.keyEntryError")
              : <T k="backend.keyEntryHint" params={{ envVar: ENV_VAR[backend] }} />}
          </Text>
          <Text size="xs" mt={4}>
            {keyPresent && (
              <>
                <Anchor size="xs" component="button" type="button" onClick={() => { setEntryOpen(false); setEntryKey(""); setEntryStatus("idle"); }}>
                  {t("backend.cancel")}
                </Anchor>
                {" · "}
              </>
            )}
            <Anchor size="xs" component="button" type="button" onClick={fetchHealth}>
              {t("backend.recheck")}
            </Anchor>
          </Text>
        </div>
      )}
    </div>
  );
}
