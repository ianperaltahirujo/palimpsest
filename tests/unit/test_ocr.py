import importlib.util
import time

import pytest

from palimpsest.config.model import OcrConfig
from palimpsest.core.errors import ConfigError, DependencyError
from palimpsest.pdf import ocr as ocr_mod


def _touch(path, content=b"data"):
    path.write_bytes(content)
    return path


def test_dependency_error_when_ocrmypdf_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    src = _touch(tmp_path / "scan.pdf")
    with pytest.raises(DependencyError):
        ocr_mod.ensure_ocr(src, tmp_path / "work", "key", OcrConfig())


def test_config_error_on_unknown_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    with pytest.raises(ConfigError):
        ocr_mod.ensure_ocr(src, tmp_path / "work", "key", OcrConfig(mode="not-a-real-mode"))


def test_reuses_existing_output_when_newer_than_source(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    work = tmp_path / "work"
    work.mkdir()
    out = _touch(work / "key_ocr.pdf")
    # Ensure the output's mtime is unambiguously >= the source's.
    now = time.time()
    import os

    os.utime(src, (now - 10, now - 10))
    os.utime(out, (now, now))

    called = []
    monkeypatch.setattr(ocr_mod.subprocess, "run", lambda *a, **kw: called.append(1))
    result = ocr_mod.ensure_ocr(src, work, "key", OcrConfig())
    assert result == out
    assert not called  # subprocess never invoked -- reused the existing output


def test_runs_ocrmypdf_and_returns_output_path(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    work = tmp_path / "work"

    class _Result:
        returncode = 0
        stderr = ""

    captured_cmd = []

    def _fake_run(cmd, env, capture_output, text):
        captured_cmd.extend(cmd)
        # ocrmypdf's real effect: it writes the output file.
        (work / "key_ocr.pdf").write_bytes(b"ocred")
        return _Result()

    monkeypatch.setattr(ocr_mod.subprocess, "run", _fake_run)
    config = OcrConfig(language="spa", mode="skip-text", oversample=400, optimize=1)
    result = ocr_mod.ensure_ocr(src, work, "key", config)
    assert result == work / "key_ocr.pdf"
    assert result.exists()
    assert "-l" in captured_cmd and "spa" in captured_cmd
    assert "--skip-text" in captured_cmd
    assert "--oversample" in captured_cmd and "400" in captured_cmd


def test_force_ocr_mode_uses_force_ocr_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    work = tmp_path / "work"

    class _Result:
        returncode = 0
        stderr = ""

    captured_cmd = []

    def _fake_run(cmd, env, capture_output, text):
        captured_cmd.extend(cmd)
        (work / "key_ocr.pdf").write_bytes(b"ocred")
        return _Result()

    monkeypatch.setattr(ocr_mod.subprocess, "run", _fake_run)
    ocr_mod.ensure_ocr(src, work, "key", OcrConfig(mode="force-ocr"))
    assert "--force-ocr" in captured_cmd
    assert "--skip-text" not in captured_cmd


def test_tessdata_prefix_set_in_subprocess_env(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    work = tmp_path / "work"

    captured_env = {}

    class _Result:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, env, capture_output, text):
        captured_env.update(env)
        (work / "key_ocr.pdf").write_bytes(b"ocred")
        return _Result()

    monkeypatch.setattr(ocr_mod.subprocess, "run", _fake_run)
    ocr_mod.ensure_ocr(src, work, "key", OcrConfig(tessdata_prefix="/custom/tessdata"))
    assert captured_env.get("TESSDATA_PREFIX") == "/custom/tessdata"


def test_nonzero_returncode_raises_dependency_error_with_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    work = tmp_path / "work"

    class _Result:
        returncode = 1
        stderr = "Could not find tesseract executable"

    monkeypatch.setattr(ocr_mod.subprocess, "run", lambda *a, **kw: _Result())
    with pytest.raises(DependencyError, match="tesseract"):
        ocr_mod.ensure_ocr(src, work, "key", OcrConfig())


def test_missing_output_file_raises_dependency_error(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    src = _touch(tmp_path / "scan.pdf")
    work = tmp_path / "work"

    class _Result:
        returncode = 0
        stderr = ""

    # Never writes the output file, even though returncode says success.
    monkeypatch.setattr(ocr_mod.subprocess, "run", lambda *a, **kw: _Result())
    with pytest.raises(DependencyError):
        ocr_mod.ensure_ocr(src, work, "key", OcrConfig())
