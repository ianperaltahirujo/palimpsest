import { createContext, useCallback, useContext, useEffect, useMemo } from "react";
import { useLocalStorage } from "@mantine/hooks";
import { STRINGS } from "./strings.js";

const I18nContext = createContext(null);

function interpolate(str, params) {
  if (!params) return str;
  return str.replace(/\{(\w+)\}/g, (m, key) => (key in params ? String(params[key]) : m));
}

export function I18nProvider({ children }) {
  const [lang, setLang] = useLocalStorage({ key: "pp-lang", defaultValue: "en" });

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const t = useCallback(
    (key, params) => {
      const dict = STRINGS[lang] || STRINGS.en;
      const raw = dict[key] ?? STRINGS.en[key] ?? key;
      return interpolate(raw, params);
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

export function useT() {
  return useI18n().t;
}

export function useLang() {
  const { lang, setLang } = useI18n();
  return [lang, setLang];
}

// Renders a dictionary string that may carry **bold** or `code` spans --
// the only markup the dictionary ever needs (see strings.js). Anything
// without those markers renders as plain text, same as t() would return.
const MARKUP_RE = /(\*\*[^*]+\*\*|`[^`]+`)/g;

export function T({ k, params }) {
  const { t } = useI18n();
  const raw = t(k, params);
  const parts = raw.split(MARKUP_RE).filter((p) => p !== "");
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={i}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}
