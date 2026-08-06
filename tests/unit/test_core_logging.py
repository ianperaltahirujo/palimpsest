import logging

from palimpsest.core.logging import configure


def test_configure_does_not_crash_under_pytest_capture(capsys):
    """The exact regression this module exists to fix: an earlier
    version called sys.stdout.reconfigure() at import time and crashed
    under pytest's output capture. configure() must be safe to call even
    when sys.stdout has been replaced by a capture object."""
    configure()
    log = logging.getLogger("palimpsest")
    log.info("hola")
    assert "hola" in capsys.readouterr().out


def test_configure_verbose_sets_debug_level():
    configure(verbose=True)
    assert logging.getLogger("palimpsest").level == logging.DEBUG


def test_configure_default_sets_info_level():
    configure(verbose=False)
    assert logging.getLogger("palimpsest").level == logging.INFO


def test_configure_does_not_propagate_to_root():
    configure()
    assert logging.getLogger("palimpsest").propagate is False


def test_configure_replaces_handlers_not_accumulates(capsys):
    configure()
    configure()
    configure()
    log = logging.getLogger("palimpsest")
    assert len(log.handlers) == 1
