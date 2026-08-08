# Security

## Reporting a vulnerability

Please open a GitHub issue, or if the report involves sensitive details,
use GitHub's private vulnerability reporting (Security tab → Report a
vulnerability) rather than a public issue.

## Scope notes specific to this project

- palimpsest processes documents that may contain sensitive personal or
  financial information (that's the use case it was built for). The tool
  itself does not transmit document content anywhere except to the
  translation backend you configure (Google Translate's public endpoint,
  or the Anthropic API if you enable that backend). Review
  `docs/configuration.md` before pointing it at sensitive documents.
- API keys are read from environment variables (`ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`), never from `palimpsest.toml` or a CLI argument, to
  avoid them landing in shell history or process listings. A gitignored
  `.env` file is one supported way to populate those variables (loaded
  by the CLI on startup) — it is still an environment-variable source,
  not a config file the tool reads keys from directly.
- The web UI's server (`palimpsest serve`) can also accept a key typed
  into the page itself (`PUT /api/keys`) — a deliberate, narrow
  exception to "keys never travel over HTTP," added specifically to
  support running the frontend somewhere other than this server (e.g. a
  GitHub Pages build) without asking the user to touch a shell or file.
  This is reachable only from the server's own origin (the built SPA it
  serves itself) or an origin the server operator explicitly
  allowlisted via `--allow-origin` (never a wildcard — see
  `server/security.py`'s `OriginCheckMiddleware`); it applies only to
  that same server process's own environment, and is written only to a
  `.env` file on that same machine — never proxied, relayed, logged, or
  echoed back in a response. The server still binds to `127.0.0.1` by
  default and has no accounts: allowlisting an origin widens WHERE a
  request can come from, not WHO the server trusts once it arrives.
