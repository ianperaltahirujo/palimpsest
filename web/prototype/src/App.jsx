import { ActionIcon, Alert, AppShell, Burger, Group, ScrollArea, Tooltip, UnstyledButton } from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import { IconAlertTriangle, IconLayoutSidebarLeftExpand } from "@tabler/icons-react";
import { AppStateProvider, useAppState } from "./state.jsx";
import { T, useT } from "./i18n.jsx";
import { MOCK, getApiBase } from "./config.js";
import Logo from "./components/Logo.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import LangToggle from "./components/LangToggle.jsx";
import Rail from "./components/Rail.jsx";
import Overview from "./components/Overview.jsx";
import Sample from "./components/Sample.jsx";
import Queue from "./components/Queue.jsx";
import Estimate from "./components/Estimate.jsx";
import Running from "./components/Running.jsx";
import Results from "./components/Results.jsx";
import DevSwitcher from "./components/DevSwitcher.jsx";

const SCREEN_COMPONENTS = {
  overview: Overview,
  sample: Sample,
  queue: Queue,
  estimate: Estimate,
  running: Running,
  results: Results,
};

// The exact command to fix "unreachable" -- only names --allow-origin
// when this page's own origin genuinely differs from the API's (the
// standalone/GitHub Pages build; see config.js's VITE_STANDALONE). A
// same-origin production build (palimpsest serve) or the npm run dev
// proxy both resolve getApiBase() to "" and need no flag at all.
export function serveCommand() {
  const apiBase = getApiBase();
  const pageOrigin = window.location.origin;
  const apiOrigin = apiBase ? new URL(apiBase, pageOrigin).origin : pageOrigin;
  return apiOrigin === pageOrigin ? "palimpsest serve" : `palimpsest serve --allow-origin ${pageOrigin}`;
}

function Shell() {
  const { screen, goto, apiError, setApiError, healthError } = useAppState();
  const t = useT();
  const [mobileOpen, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopCollapsed, setDesktopCollapsed] = useLocalStorage({ key: "pp-rail-collapsed", defaultValue: false });
  const ScreenComponent = SCREEN_COMPONENTS[screen] ?? Overview;
  const showSuggested = screen !== "overview" && screen !== "sample";

  return (
    <AppShell
      header={{ height: 58 }}
      navbar={{ width: 296, breakpoint: "md", collapsed: { mobile: !mobileOpen, desktop: desktopCollapsed } }}
      padding={0}
    >
      <AppShell.Header>
        <Group h="100%" px={20} justify="space-between">
          <Group gap={14}>
            <Burger opened={mobileOpen} onClick={toggleMobile} hiddenFrom="md" size="sm" aria-label={t("app.toggleSettings")} />
            <UnstyledButton
              onClick={() => goto("overview")}
              aria-label={t("app.brandAria")}
              className="pp-brand"
              style={{ display: "flex", alignItems: "center", gap: 9, fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 800, fontStretch: "118%", fontSize: 16.5 }}
            >
              <Logo />
              palimpsest
            </UnstyledButton>
          </Group>
          <Group gap={10}>
            <LangToggle />
            <ThemeToggle />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar>
        <AppShell.Section grow component={ScrollArea}>
          <Rail showSuggested={showSuggested} onCollapse={() => setDesktopCollapsed(true)} />
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        {!MOCK && apiError && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            color="flag"
            variant="light"
            withCloseButton
            onClose={() => setApiError(null)}
            m={20}
            title={t("app.backendUnreachable")}
          >
            {apiError.message}
          </Alert>
        )}
        {/* Only when apiError isn't already showing -- both are driven by
            the same underlying "can't reach the server" fact and
            stacking them would just repeat it. This one is health-probe
            driven (state.jsx), so unlike apiError it doesn't need a user
            action to appear -- it's live on load, and on every backend
            selected (BackendSelector's own inline notice used to disappear
            entirely for the "google" backend, which needs no key but
            still needs a reachable server for translation itself). Not
            dismissible: it reflects current health, not a one-time event,
            and disappears on its own the moment a probe succeeds. */}
        {!MOCK && !apiError && healthError && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            color="flag"
            variant="light"
            m={20}
            title={t("app.backendUnreachable")}
          >
            <T k="app.serverUnreachableBody" params={{ cmd: serveCommand() }} />
          </Alert>
        )}
        <ScreenComponent />
      </AppShell.Main>

      {/* The sidebar's own collapse button is unreachable once it's
          hidden -- this small edge tab is the only way back in, same
          idiom as the pass-2 prototype's .rail-reveal. */}
      {desktopCollapsed && (
        <Tooltip label={t("app.showSidebar")} position="right">
          <ActionIcon
            variant="default"
            onClick={() => setDesktopCollapsed(false)}
            visibleFrom="md"
            aria-label={t("app.showSidebar")}
            style={{ position: "fixed", left: 0, top: 70, zIndex: 200, borderRadius: "0 6px 6px 0", borderLeft: "none" }}
          >
            <IconLayoutSidebarLeftExpand size={16} />
          </ActionIcon>
        </Tooltip>
      )}

      {MOCK && <DevSwitcher />}
    </AppShell>
  );
}

export default function App() {
  return (
    <AppStateProvider>
      <Shell />
    </AppStateProvider>
  );
}
