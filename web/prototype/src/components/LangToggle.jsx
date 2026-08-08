import { ActionIcon, Tooltip } from "@mantine/core";
import { useLang, useT } from "../i18n.jsx";

// Shows the flag of the CURRENT language (not the one you'd switch to) --
// same idiom as the theme toggle showing the current sun/moon state.
// Clicking flips en <-> es. Inline SVG, not an asset file, so there's no
// loading flash and nothing to add under public/.
function UKFlag(props) {
  return (
    <svg viewBox="0 0 60 40" {...props}>
      <rect width="60" height="40" fill="#00247d" />
      <path d="M0,0 60,40 M60,0 0,40" stroke="#fff" strokeWidth="8" />
      <path d="M0,0 60,40 M60,0 0,40" stroke="#cf142b" strokeWidth="4" />
      <path d="M30,0 30,40 M0,20 60,20" stroke="#fff" strokeWidth="14" />
      <path d="M30,0 30,40 M0,20 60,20" stroke="#cf142b" strokeWidth="8" />
    </svg>
  );
}

function SpainFlag(props) {
  return (
    <svg viewBox="0 0 60 40" {...props}>
      <rect width="60" height="40" fill="#c60b1e" />
      <rect y="10" width="60" height="20" fill="#ffc400" />
    </svg>
  );
}

export default function LangToggle() {
  const [lang, setLang] = useLang();
  const t = useT();
  const nextLang = lang === "en" ? "es" : "en";
  const label = t("lang.switchTo", { lang: lang === "en" ? t("lang.spanish") : t("lang.english") });

  return (
    <Tooltip label={label}>
      {/* variant="subtle" -- same lg size (34px) as the theme toggle
          next to it, but no border: the flag's own colour is the
          affordance, an outline around it would double up. The flag
          fills almost the full button and picks up the button's own
          radius so its corners curve exactly like the theme toggle's. */}
      <ActionIcon variant="subtle" color="gray" size="lg" onClick={() => setLang(nextLang)} aria-label={label}>
        {lang === "en" ? (
          <UKFlag width={24} height={16} style={{ borderRadius: "var(--mantine-radius-default)", overflow: "hidden", display: "block" }} />
        ) : (
          <SpainFlag width={24} height={16} style={{ borderRadius: "var(--mantine-radius-default)", overflow: "hidden", display: "block" }} />
        )}
      </ActionIcon>
    </Tooltip>
  );
}
