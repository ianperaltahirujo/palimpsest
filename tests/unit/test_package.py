import subprocess
import sys

from palimpsest import __version__
from palimpsest.cli import build_parser


def test_version_is_a_string():
    assert isinstance(__version__, str) and __version__


def test_cli_parser_builds():
    parser = build_parser()
    assert parser.prog == "palimpsest"


def test_console_script_runs():
    result = subprocess.run(
        [sys.executable, "-m", "palimpsest", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "palimpsest" in result.stdout
