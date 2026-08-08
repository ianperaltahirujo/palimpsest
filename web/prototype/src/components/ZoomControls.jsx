import { ActionIcon, Text } from "@mantine/core";
import { IconMinus, IconPlus } from "@tabler/icons-react";
import { useT } from "../i18n.jsx";

export default function ZoomControls({ zoom, zoomIn, zoomOut, resetZoom, atMin, atMax }) {
  const t = useT();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
      <ActionIcon variant="default" size="sm" disabled={atMin} onClick={zoomOut} aria-label={t("zoom.out")}>
        <IconMinus size={13} />
      </ActionIcon>
      <Text
        component="button"
        onClick={resetZoom}
        size="xs"
        ff="monospace"
        c="dimmed"
        style={{ width: 42, textAlign: "center", background: "none", border: "none", cursor: "pointer" }}
        title={t("zoom.reset")}
      >
        {Math.round(zoom * 100)}%
      </Text>
      <ActionIcon variant="default" size="sm" disabled={atMax} onClick={zoomIn} aria-label={t("zoom.in")}>
        <IconPlus size={13} />
      </ActionIcon>
    </div>
  );
}
