// Two pages in register -- two overlapping page outlines, offset
// diagonally, converging into alignment on hover. "Same page, two
// languages, exactly aligned." Recolored to an aged-manuscript palette
// (indigo ink over an oxblood page showing through) so the mark itself
// reads as an old, scraped-and-rewritten document -- what "palimpsest"
// actually names. Shares the .pp-regmark/.pp-m/.pp-u hover choreography
// from index.css, which reads its colours from
// --pp-logo-upper/--pp-logo-lower.
const PALETTE = { upper: "#2E3B63", lower: "#7A2E2E" };

export default function Logo({ className = "" }) {
  return (
    <svg
      className={"pp-regmark " + className}
      viewBox="0 0 24 24"
      aria-hidden="true"
      width={19}
      height={19}
      style={{ "--pp-logo-upper": PALETTE.upper, "--pp-logo-lower": PALETTE.lower }}
    >
      <g className="pp-m">
        <rect x="3" y="4" width="14.5" height="17.5" rx="1.1" fill="none" strokeWidth="1.3" />
      </g>
      <g className="pp-u">
        <rect x="6.5" y="2.5" width="14.5" height="17.5" rx="1.1" fill="none" strokeWidth="1.3" />
      </g>
    </svg>
  );
}
