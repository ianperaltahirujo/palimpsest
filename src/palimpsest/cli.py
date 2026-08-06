"""Command-line entry point.

Subcommands (translate, batch, compare, cache, audit, config) land in PR7
alongside the pipelines they drive. For now this only proves the package
installs and the console script resolves.
"""

from __future__ import annotations

import argparse
import sys

from palimpsest import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="palimpsest", description=__doc__)
    parser.add_argument("--version", action="version", version=f"palimpsest {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
