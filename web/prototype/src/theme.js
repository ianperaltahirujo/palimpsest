import { createTheme } from "@mantine/core";

// The Registration system's two semantic hues (--register = translated
// layer, --under = original layer) plus --flag (attention) and --ok
// (success), carried into Mantine as named color scales. Index 6 in each
// ramp is the source hex from the static prototype's :root tokens -- see
// index.css for the raw hex values, which bespoke CSS (page-stack, wipe,
// pbox) still reads directly rather than through Mantine's color system.
//
// Generated in HSL holding saturation constant end to end (index 0 ~96%L,
// index 9 ~20-38%L depending on how dark the source already is), matching
// how Mantine's own scales are built -- e.g. blue[9] is #1864ab, not near-
// black. Mixing toward black (the first version of this file did) starves
// index 7-9 of saturation, and every `variant="light"` background --
// Badge, Alert, the status tags on Results -- is DERIVED from the dark
// end of the scale (--mantine-color-{c}-light). A ramp that goes achromatic
// at the dark end makes every one of those renders as flat grey. Regenerate
// with the small script in this file's git history if the source hexes
// ever change; never hand-mix toward black or white again.
export const theme = createTheme({
  primaryColor: "register",
  primaryShade: { light: 6, dark: 4 },
  colors: {
    register: ["#ecf3fe", "#cfe2fc", "#9ec5fa", "#6ea8f7", "#3d8bf5", "#1674f3", "#0B5FD0", "#094ba5", "#073c83", "#052c61"],
    under: ["#fcedf5", "#f8d3e7", "#f2a6ce", "#eb7ab6", "#e44e9d", "#df2a8a", "#C81E78", "#9c175d", "#781248", "#590d35"],
    flag: ["#fef1ec", "#fcdccf", "#f9b99f", "#f6966f", "#f3733f", "#f15718", "#C2410C", "#a3370a", "#822b08", "#602006"],
    ok: ["#eefcf7", "#d4f7ec", "#a8f0d9", "#7de8c7", "#52e0b4", "#2fdaa5", "#147154", "#1a936e", "#157557", "#0f5740"],
  },
  fontFamily: '"IBM Plex Sans", -apple-system, "Segoe UI", sans-serif',
  fontFamilyMonospace: '"IBM Plex Mono", ui-monospace, "SFMono-Regular", Consolas, monospace',
  headings: {
    fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif',
    fontWeight: "800",
  },
  defaultRadius: "3px",
  radius: { xs: "2px", sm: "3px", md: "6px", lg: "8px", xl: "12px" },
  components: {
    Button: {
      defaultProps: { radius: "3px" },
    },
  },
});

// Vendor identity colours (Part B of the pass-3 plan). Deliberately kept
// OUT of the Mantine theme's `colors` -- the Registration system uses
// register/under semantically (translated vs. original layer) and mixing
// a third, non-semantic palette into that namespace risks a vendor hue
// leaking somewhere it shouldn't. These are consumed directly by
// BackendSelector.jsx and nowhere else in the app.
export const VENDOR_COLORS = {
  gemini: "linear-gradient(135deg, #4796E3, #9177C7)",
  anthropic: "#D97757",
  google: "#4285F4",
};
