import { createTheme, virtualColor } from "@mantine/core";

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
//
// One caveat this recipe genuinely can't paper over: the shared lightness
// ladder bottoms out at index 9 = L20%, half of where Mantine's own scales
// sit (red[9]/yellow[9]/etc. are L35-48%). darken(scale[9], .5) is what
// EVERY `variant="light"` background resolves to in dark mode, so at L20
// that background is always near-black regardless of hue -- see `warn`
// below for the one place this actually mattered and how it's handled.
export const theme = createTheme({
  primaryColor: "register",
  primaryShade: { light: 6, dark: 4 },
  colors: {
    register: ["#ecf3fe", "#cfe2fc", "#9ec5fa", "#6ea8f7", "#3d8bf5", "#1674f3", "#0B5FD0", "#094ba5", "#073c83", "#052c61"],
    under: ["#fcedf5", "#f8d3e7", "#f2a6ce", "#eb7ab6", "#e44e9d", "#df2a8a", "#C81E78", "#9c175d", "#781248", "#590d35"],
    flag: ["#fef1ec", "#fcdccf", "#f9b99f", "#f6966f", "#f3733f", "#f15718", "#C2410C", "#a3370a", "#822b08", "#602006"],
    ok: ["#eefcf7", "#d4f7ec", "#a8f0d9", "#7de8c7", "#52e0b4", "#2fdaa5", "#147154", "#1a936e", "#157557", "#0f5740"],
    // `warn` -- the amber attention hue, for things that are slow or
    // unknowable rather than wrong. `flag` keeps meaning ERROR (failed
    // notifications, the unreachable banner); warn means "this will cost
    // you time or certainty".
    //
    // Split behind a virtualColor because the two schemes read index 9 for
    // opposite purposes. In light, index 9 is RENDERED TEXT
    // (--mantine-color-warn-light-color) on the index-1 tint, so it has to
    // stay dark enough to read. In dark, index 9 is never drawn at all --
    // Mantine only uses it as the seed for darken(x, .5) ->
    // --mantine-color-warn-light, the Alert/Badge background. An earlier
    // version of this ramp held S~88 end to end (Mantine's own recipe),
    // which made the Alert/Badge read as a bold, saturated amber instead
    // of the "this will cost you time" tone it's meant to have -- S is
    // deliberately held low (~34) across every index here instead, so both
    // the light-mode tint and the darken(x,.5) dark-mode background come
    // out muted/dim rather than vivid, not just pale. Index 9 in the dark
    // ramp is ALSO lifted (L22 -> L30) same as before, so the darkened
    // background still clears the L20-floor problem documented above
    // instead of going near-black. The two ramps are byte-identical at
    // indices 0-8; do not "tidy" them into one.
    warnLight: ["#FAF9F5", "#F4F1E9", "#E7E1CF", "#D7CBAD", "#C4B387", "#B39E65", "#9A844C", "#7B6A3D", "#635531", "#4B4125"],
    warnDark: ["#FAF9F5", "#F4F1E9", "#E7E1CF", "#D7CBAD", "#C4B387", "#B39E65", "#9A844C", "#7B6A3D", "#635531", "#675832"],
    warn: virtualColor({ name: "warn", light: "warnLight", dark: "warnDark" }),
    // `accept` -- a dim, muted sibling of `register`'s own hue, used ONLY
    // for the upload Dropzone's drag-accept state (Overview.jsx,
    // Sample.jsx). `register` itself is `primaryColor` -- every default
    // Button site-wide reads its `-filled` shade, so it can't be
    // desaturated without washing out every CTA in the app. This is a
    // separate scale at the same hue so the dropzone still reads as "the
    // app's blue," just dim instead of a bold filled block. Same
    // low-saturation/lifted-index-9 recipe as `warn`, same reasoning.
    acceptLight: ["#F5F7FA", "#E8EEF4", "#CED9E8", "#ACBED8", "#86A1C6", "#6386B6", "#496D9C", "#3B577D", "#2F4665", "#24354C"],
    acceptDark: ["#F5F7FA", "#E8EEF4", "#CED9E8", "#ACBED8", "#86A1C6", "#6386B6", "#496D9C", "#3B577D", "#2F4665", "#314868"],
    accept: virtualColor({ name: "accept", light: "acceptLight", dark: "acceptDark" }),
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
