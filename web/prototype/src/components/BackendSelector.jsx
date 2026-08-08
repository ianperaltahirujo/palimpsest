import { useEffect, useState } from "react";
import { Anchor, Box, PasswordInput, Radio, Text, TextInput } from "@mantine/core";
import { VENDOR_COLORS } from "../theme.js";
import { BACKEND_COPY } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { T, useT } from "../i18n.jsx";
import { MOCK, getApiBase, setApiBase } from "../config.js";
import { clearCachedKey, ENV_VAR, getCachedKey, HEALTH_KEY, setCachedKey } from "../keys.js";

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
  const { selectedBackend, setSelectedBackend, health, refreshHealth } = useAppState();

  // MOCK mode keeps its own local state and the fake key-check flow
  // exactly as before. Real mode reads/writes the shared selectedBackend
  // (state.jsx) so Estimate's "Translate" button submits the same
  // backend this control shows selected.
  const [mockBackend, setMockBackend] = useState("gemini");
  const [apiKey, setApiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState("idle"); // idle | checking | ok | empty
  const [addressOpen, setAddressOpen] = useState(false);
  const [addressDraft, setAddressDraft] = useState(() => getApiBase());
  const [entryOpen, setEntryOpen] = useState(false);
  const [entryKey, setEntryKey] = useState("");
  const [entryStatus, setEntryStatus] = useState("idle"); // idle | saving | error
  const [pwVisible, setPwVisible] = useState(false);
  const [cachedKeyValue, setCachedKeyValue] = useState(null);

  const backend = MOCK ? mockBackend : selectedBackend || "gemini";
  const copy = BACKEND_COPY[backend];

  // Re-read the browser-cached key whenever the selected backend changes
  // (each backend has its own cache slot -- see keys.js) rather than
  // re-reading localStorage on every render. Also resets the entry-form
  // state, which is otherwise shared across backends by construction (one
  // component instance, not one per backend) -- caught in manual browser
  // testing: without this, a failed save on backend A (e.g. attempted
  // while offline) left entryStatus === "error" sitting in state, and
  // switching to backend B's freshly-opened, never-touched entry form
  // showed A's stale error message.
  useEffect(() => {
    if (MOCK) return;
    setCachedKeyValue(getCachedKey(backend));
    setEntryOpen(false);
    setEntryKey("");
    setEntryStatus("idle");
    setPwVisible(false);
  }, [backend]);

  function saveAddress() {
    setApiBase(addressDraft.trim());
    setAddressDraft(getApiBase());
    setAddressOpen(false);
    refreshHealth();
  }

  // Always caches the key locally first -- this is what makes the box
  // usable with no server reachable at all, the whole point of this
  // change. refreshHealth() (state.jsx) already auto-pushes any cached
  // key the moment a probe finds it absent server-side, so calling it
  // here (rather than also calling api.setKeys() directly) is enough to
  // push immediately when a server IS reachable, with no separate/
  // duplicate push path to keep in sync.
  function submitEntryKey() {
    const value = entryKey.trim();
    if (!value) return;
    setCachedKey(backend, value);
    setCachedKeyValue(value);
    setPwVisible(false); // never leave a just-submitted secret visible on screen
    setEntryKey("");
    setEntryOpen(false);
    setEntryStatus("saving");
    refreshHealth()
      .then(() => setEntryStatus("idle"))
      .catch(() => setEntryStatus("error"));
  }

  function forgetKey() {
    clearCachedKey(backend);
    setCachedKeyValue(null);
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
    setPwVisible(false);
    setTimeout(() => setKeyStatus("ok"), 650);
  }

  const keyPresentOnServer = health?.[HEALTH_KEY[backend]];

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
          {/* The Check button is a sibling, not a rightSection override --
              PasswordInput's OWN rightSection is its visibility-toggle eye
              icon, and overriding it would silently remove the only way to
              reveal what was typed before submitting. */}
          <Box style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
            <PasswordInput
              style={{ flex: 1 }}
              label={t("backend.apiKeyLabel")}
              placeholder="AIza..."
              size="sm"
              value={apiKey}
              visible={pwVisible}
              onVisibilityChange={setPwVisible}
              onChange={(e) => setApiKey(e.currentTarget.value)}
            />
            <button className="pp-btn-mini" onClick={checkKey}>
              {t("backend.check")}
            </button>
          </Box>
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

      {/* Real mode: the key box is ALWAYS visible and usable, regardless
          of whether a server is reachable right now -- that's the whole
          point of caching a submitted key locally (keys.js) instead of
          gating this section behind a health check. Server reachability
          gets its own app-level banner (App.jsx), not a block here. */}
      {copy.needsKey && !MOCK && (
        <div style={{ marginTop: 10 }}>
          {keyPresentOnServer && !entryOpen ? (
            <>
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
                <Anchor size="xs" component="button" type="button" onClick={refreshHealth}>
                  {t("backend.recheck")}
                </Anchor>
              </Text>
            </>
          ) : cachedKeyValue && !entryOpen ? (
            <>
              <Text size="xs" fw={600} c="dimmed">
                {t("backend.keyCachedLocally")}
              </Text>
              <Text size="xs" mt={6}>
                <Anchor size="xs" component="button" type="button" onClick={() => setEntryOpen(true)}>
                  {t("backend.keyChange")}
                </Anchor>
                {" · "}
                <Anchor size="xs" component="button" type="button" onClick={forgetKey}>
                  {t("backend.keyForget")}
                </Anchor>
                {" · "}
                <Anchor size="xs" component="button" type="button" onClick={refreshHealth}>
                  {t("backend.recheck")}
                </Anchor>
              </Text>
            </>
          ) : (
            <>
              {/* Save is a sibling, not a rightSection override -- see the
                  MOCK-mode block above for why that matters here. */}
              <Box style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
                <PasswordInput
                  style={{ flex: 1 }}
                  label={t("backend.apiKeyLabel")}
                  placeholder={backend === "anthropic" ? "sk-ant-..." : "AIza..."}
                  size="sm"
                  value={entryKey}
                  visible={pwVisible}
                  onVisibilityChange={setPwVisible}
                  onChange={(e) => {
                    setEntryKey(e.currentTarget.value);
                    setEntryStatus("idle");
                  }}
                  onKeyDown={(e) => e.key === "Enter" && submitEntryKey()}
                />
                <button className="pp-btn-mini" onClick={submitEntryKey}>
                  {entryStatus === "saving" ? t("backend.keyEntrySaving") : t("backend.keyEntrySave")}
                </button>
              </Box>
              <Text size="xs" mt={7} c={entryStatus === "error" ? "flag" : "dimmed"}>
                {entryStatus === "error"
                  ? t("backend.keyEntryError")
                  : <T k="backend.keyEntryHint" params={{ envVar: ENV_VAR[backend] }} />}
              </Text>
              <Text size="xs" mt={4}>
                {(keyPresentOnServer || cachedKeyValue) && (
                  <>
                    <Anchor
                      size="xs" component="button" type="button"
                      onClick={() => { setEntryOpen(false); setEntryKey(""); setEntryStatus("idle"); }}
                    >
                      {t("backend.cancel")}
                    </Anchor>
                    {" · "}
                  </>
                )}
                <Anchor size="xs" component="button" type="button" onClick={refreshHealth}>
                  {t("backend.recheck")}
                </Anchor>
              </Text>
            </>
          )}
        </div>
      )}
    </div>
  );
}
