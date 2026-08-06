# Contributing

This project is in early, staged development (see the open PRs for the
current rollout plan). A couple of rules that are load-bearing for how it
was extracted from a real client pipeline:

- **Never commit anything under `private/`, `.palimpsest/`, or `corpus/`.**
  These paths are reserved for user-specific document maps, entity lists,
  and translation caches, and are gitignored for a reason — the project's
  own origin included real confidential client data that had to be kept
  out.
- **Run `python tools/scrub_check.py --history` before opening a PR** if
  you've added or edited anything under `docs/` or `examples/`. It's also
  enforced in CI.
- No test may make a real network call. Mark anything that legitimately
  needs one `@pytest.mark.network` — it will be skipped in CI by default.

Beyond that: open an issue before a large PR, keep changes scoped to one
concern, and prefer extending an existing module over introducing a new
abstraction layer.
