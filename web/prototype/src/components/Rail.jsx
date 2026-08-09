import { useEffect, useRef, useState } from "react";
import { ActionIcon, Box, Group, Menu, Text, TextInput, Tooltip } from "@mantine/core";
import { IconLayoutSidebarLeftCollapse } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import BackendSelector from "./BackendSelector.jsx";
import { PROTECTED_ENTITIES, SUGGESTED_ENTITIES } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import * as api from "../api.js";
import { deleteProfile, getProfiles, saveProfile } from "../profiles.js";

const GROUPS = ["companies", "people", "places", "other"];
const EMPTY_GROUPS = { companies: [], people: [], places: [], other: [] };

export default function Rail({ showSuggested, onCollapse }) {
  const t = useT();
  // MOCK-only fixtures -- real mode starts empty and stays empty until
  // GET /api/entities actually answers (below). Seeding real mode from
  // the fixture was a real bug: on a failed fetch the fake "Grupo
  // Meridian"/"Banco Litoral"/"Andres Carreno" names stayed on screen
  // forever, and worse, apply() PUTs the whole roster back to the server
  // on any edit -- so adding one real entity while the fixture was still
  // showing would write the fictional names into the user's actual
  // entities.toml.
  const [groups, setGroups] = useState(() => (MOCK ? structuredClone(PROTECTED_ENTITIES) : EMPTY_GROUPS));
  const [suggested, setSuggested] = useState(() => (MOCK ? SUGGESTED_ENTITIES : []));
  const [draft, setDraft] = useState("");
  const [dropTarget, setDropTarget] = useState(null);
  // Profiles live in localStorage (see profiles.js's own docstring for
  // why -- server-side entities are one shared global file, not scoped
  // per visitor, so saving a profile there would leak across visitors).
  // Read once at mount and kept in local state, refreshed after every
  // save/delete -- nothing else in this app writes pp-entity-profiles.
  const [profiles, setProfiles] = useState(() => getProfiles());
  const [profileName, setProfileName] = useState("");
  // The pre-clear snapshot "Remove all" stashes so its Undo notification
  // can restore it -- a ref, not state, since it never drives a render
  // on its own.
  const preClearSnapshotRef = useRef(null);
  const count = Object.values(groups).reduce((n, g) => n + g.length, 0);

  useEffect(() => {
    if (MOCK) return;
    // Silent on failure -- this fires on mount, before the visitor has
    // done anything, and a new visitor with no server set up yet WILL
    // fail this fetch every time. Falling back to EMPTY_GROUPS already
    // reads as "nothing configured", so there's nothing actionable to
    // toast; App.jsx's unreachable banner + setup hint own telling them
    // why once they've actually started (touched the dropzone).
    api.getEntities().then(setGroups).catch(() => {});
  }, []);

  // Every mutation goes through this so real mode PUTs the new roster
  // to the server right after updating local state -- fire-and-forget,
  // with a toast on failure rather than blocking the UI on the round
  // trip (the local state change is what the user sees immediately).
  function apply(updater) {
    setGroups((prev) => {
      const next = updater(prev);
      if (!MOCK) {
        api.putEntities(next).catch((e) => notifications.show({ message: e.message, color: "flag" }));
      }
      return next;
    });
  }

  function addEntity(text, group = "other") {
    const v = text.trim();
    if (!v) return;
    apply((g) => ({ ...g, [group]: [...g[group], v] }));
  }
  function removeEntity(group, value) {
    apply((g) => ({ ...g, [group]: g[group].filter((v) => v !== value) }));
  }
  function moveEntity(fromGroup, value, toGroup) {
    if (fromGroup === toGroup) return;
    apply((g) => ({
      ...g,
      [fromGroup]: g[fromGroup].filter((v) => v !== value),
      [toGroup]: [...g[toGroup], value],
    }));
  }
  function acceptSuggested(value) {
    addEntity(value, "other");
    setSuggested((s) => s.filter((v) => v !== value));
  }

  function exportToml() {
    let toml = "[entities]\n";
    for (const g of GROUPS) {
      toml += g + " = [" + groups[g].map((v) => JSON.stringify(v)).join(", ") + "]\n";
    }
    const blob = new Blob([toml], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "entities.toml";
    a.click();
  }

  function handleSaveProfile() {
    const name = profileName.trim();
    if (!name) return;
    setProfiles(saveProfile(name, groups));
    setProfileName("");
    notifications.show({ message: t("rail.profileSaved", { name }) });
  }
  function handleLoadProfile(profile) {
    apply(() => structuredClone(profile.groups));
  }
  function handleDeleteProfile(id) {
    setProfiles(deleteProfile(id));
  }

  // No confirmation dialog -- the user gets Undo instead, which is meant
  // to happen immediately after a misclick, not behind an extra prompt.
  function handleRemoveAll() {
    preClearSnapshotRef.current = groups;
    apply(() => structuredClone(EMPTY_GROUPS));
    const notificationId = "rail-remove-all-undo";
    notifications.show({
      id: notificationId,
      color: "flag",
      autoClose: 8000,
      message: (
        <Group justify="space-between" gap={12} wrap="nowrap">
          <Text size="sm">{t("rail.removedAllNotice")}</Text>
          <button className="pp-link-btn" onClick={() => handleUndoRemoveAll(notificationId)}>
            {t("rail.undo")}
          </button>
        </Group>
      ),
    });
  }
  function handleUndoRemoveAll(notificationId) {
    const snapshot = preClearSnapshotRef.current;
    if (!snapshot) return;
    apply(() => snapshot);
    preClearSnapshotRef.current = null;
    notifications.hide(notificationId);
  }

  function onChipDragStart(e, group, value) {
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("application/json", JSON.stringify({ from: group, value }));
  }
  function onZoneDragOver(e, group) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dropTarget !== group) setDropTarget(group);
  }
  function onZoneDragLeave(group) {
    setDropTarget((z) => (z === group ? null : z));
  }
  function onZoneDrop(e, group) {
    e.preventDefault();
    setDropTarget(null);
    let payload;
    try {
      payload = JSON.parse(e.dataTransfer.getData("application/json"));
    } catch {
      return;
    }
    if (!payload?.from || !payload?.value) return;
    moveEntity(payload.from, payload.value, group);
  }

  return (
    <Box style={{ padding: "26px 18px 40px" }}>
      <div style={{ marginBottom: 20 }}>
        <Group justify="space-between" mb={11}>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" ff="monospace" style={{ letterSpacing: ".09em" }}>
            {t("rail.backend")}
          </Text>
          <Tooltip label={t("rail.hideSidebar")}>
            <ActionIcon variant="subtle" color="gray" size="sm" onClick={onCollapse} aria-label={t("rail.hideSidebar")}>
              <IconLayoutSidebarLeftCollapse size={15} />
            </ActionIcon>
          </Tooltip>
        </Group>
        <BackendSelector />
      </div>

      <div style={{ borderTop: "1px solid var(--pp-rule-soft)", paddingTop: 18 }}>
        <Group justify="space-between" mb={11}>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" ff="monospace" style={{ letterSpacing: ".09em" }}>
            {t("rail.protectedEntities")}
          </Text>
          <Text size="xs" c="dimmed" ff="monospace">
            {count}
          </Text>
        </Group>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {GROUPS.map((g) => {
            const values = groups[g];
            const isOver = dropTarget === g;
            return (
              <div key={g}>
                <Text size="10px" tt="uppercase" c="dimmed" ff="monospace" mb={6} style={{ letterSpacing: ".08em" }}>
                  {t(`rail.group.${g}`)}
                </Text>
                <div
                  className={"pp-drop-zone" + (isOver ? " over" : "") + (values.length ? "" : " empty")}
                  onDragOver={(e) => onZoneDragOver(e, g)}
                  onDragLeave={() => onZoneDragLeave(g)}
                  onDrop={(e) => onZoneDrop(e, g)}
                  style={{ display: "flex", flexWrap: "wrap", gap: 6 }}
                >
                  {values.map((v) => (
                    <span
                      key={v}
                      className="pp-chip"
                      draggable
                      onDragStart={(e) => onChipDragStart(e, g, v)}
                    >
                      <Menu withinPortal position="bottom-start" shadow="md">
                        <Menu.Target>
                          <span style={{ cursor: "grab" }}>{v}</span>
                        </Menu.Target>
                        <Menu.Dropdown>
                          {GROUPS.filter((dest) => dest !== g).map((dest) => (
                            <Menu.Item key={dest} onClick={() => moveEntity(g, v, dest)}>
                              {t("rail.moveTo", { group: t(`rail.group.${dest}`) })}
                            </Menu.Item>
                          ))}
                        </Menu.Dropdown>
                      </Menu>
                      <button aria-label={t("rail.removeAria", { value: v })} onClick={() => removeEntity(g, v)}>
                        ×
                      </button>
                    </span>
                  ))}
                  {values.length === 0 && (
                    <Text size="11px" c="dimmed" fs="italic">
                      {t("rail.dropHere")}
                    </Text>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <Group gap={6} mt={10} wrap="nowrap">
          <TextInput
            size="xs"
            style={{ flex: 1 }}
            placeholder={t("rail.addPlaceholder")}
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                addEntity(draft);
                setDraft("");
              }
            }}
          />
          <button className="pp-btn-mini" onClick={() => { addEntity(draft); setDraft(""); }}>
            {t("rail.add")}
          </button>
        </Group>
        <Text size="11px" c="dimmed" mt={6}>
          {t("rail.caseNote").split(/(`[^`]+`)/).map((part, i) =>
            part.startsWith("`") ? <code key={i}>{part.slice(1, -1)}</code> : part,
          )}
        </Text>
        <Group gap={14} mt={10}>
          <button
            className="pp-link-btn"
            onClick={() => notifications.show({ message: t("rail.importNotice") })}
          >
            {t("rail.importToml")}
          </button>
          <button className="pp-link-btn" onClick={exportToml}>
            {t("rail.exportToml")}
          </button>
          {count > 0 && (
            <button className="pp-link-btn" onClick={handleRemoveAll}>
              {t("rail.removeAll")}
            </button>
          )}
        </Group>
      </div>

      <div style={{ borderTop: "1px solid var(--pp-rule-soft)", paddingTop: 18, marginTop: 18 }}>
        <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={11} ff="monospace" style={{ letterSpacing: ".09em" }}>
          {t("rail.profiles")}
        </Text>
        {profiles.length === 0 ? (
          <Text size="11px" c="dimmed" fs="italic">
            {t("rail.noProfiles")}
          </Text>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {profiles.map((p) => (
              <Group key={p.id} justify="space-between" gap={6} wrap="nowrap">
                <button
                  className="pp-link-btn"
                  aria-label={t("rail.loadProfile", { name: p.name })}
                  onClick={() => handleLoadProfile(p)}
                  style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                >
                  {p.name}
                </button>
                <button
                  aria-label={t("rail.deleteProfile", { name: p.name })}
                  onClick={() => handleDeleteProfile(p.id)}
                >
                  ×
                </button>
              </Group>
            ))}
          </div>
        )}
        <Group gap={6} mt={10} wrap="nowrap">
          <TextInput
            size="xs"
            style={{ flex: 1 }}
            placeholder={t("rail.profileNamePlaceholder")}
            value={profileName}
            onChange={(e) => setProfileName(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSaveProfile();
            }}
          />
          <button
            className="pp-btn-mini"
            aria-label={t("rail.saveProfileAria")}
            onClick={handleSaveProfile}
            disabled={count === 0}
          >
            {t("rail.saveProfile")}
          </button>
        </Group>
      </div>

      {showSuggested && suggested.length > 0 && (
        <div style={{ borderTop: "1px solid var(--pp-rule-soft)", paddingTop: 18, marginTop: 18 }}>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={11} ff="monospace" style={{ letterSpacing: ".09em" }}>
            {t("rail.suggested")}
          </Text>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {suggested.map((v) => (
              <span className="pp-chip pp-chip--suggested" key={v} onClick={() => acceptSuggested(v)}>
                + {v}
              </span>
            ))}
          </div>
          <Text size="11px" c="dimmed" mt={6}>
            {t("rail.suggestedNote")}
          </Text>
        </div>
      )}
    </Box>
  );
}
