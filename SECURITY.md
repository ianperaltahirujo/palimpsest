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
- API keys are read only from environment variables
  (`ANTHROPIC_API_KEY`), never from a config file or CLI argument, to
  avoid them landing in shell history or process listings. A gitignored
  `.env` file is one supported way to populate those variables (loaded by
  the CLI on startup) — it is still an environment-variable source, not a
  config file the tool reads keys from directly.
