import { ActionIcon, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { useT } from "../i18n.jsx";

// Sun/moon morph -- see index.css for the mask-circle animation. Reads the
// EFFECTIVE scheme (useComputedColorScheme, never "auto") so the icon is
// correct on first paint under system dark mode, not just after a click.
export default function ThemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("light");
  const t = useT();

  return (
    <ActionIcon
      variant="default"
      size="lg"
      aria-label={t("theme.toggle")}
      title={t("theme.toggle")}
      onClick={() => setColorScheme(computed === "dark" ? "light" : "dark")}
    >
      <svg className="pp-theme-icon" data-icon={computed} width={15} height={15} viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <defs>
          <mask id="ppMoonMask" maskUnits="userSpaceOnUse">
            <rect x="0" y="0" width="16" height="16" fill="#fff" />
            <circle className="pp-theme-moon-cut" cx="20" cy="4.6" r="5.4" fill="#000" />
          </mask>
        </defs>
        <g className="pp-theme-rays" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <line x1="8" y1="0.5" x2="8" y2="2.2" />
          <line x1="8" y1="13.8" x2="8" y2="15.5" />
          <line x1="0.5" y1="8" x2="2.2" y2="8" />
          <line x1="13.8" y1="8" x2="15.5" y2="8" />
          <line x1="2.6" y1="2.6" x2="3.8" y2="3.8" />
          <line x1="12.2" y1="12.2" x2="13.4" y2="13.4" />
          <line x1="2.6" y1="13.4" x2="3.8" y2="12.2" />
          <line x1="12.2" y1="3.8" x2="13.4" y2="2.6" />
        </g>
        <circle cx="8" cy="8" r="4.3" fill="currentColor" mask="url(#ppMoonMask)" />
      </svg>
    </ActionIcon>
  );
}
