"""Unit tests for `cli.cmd_serve`'s static-mount/origin wiring -- no real
server is started; `create_app`/`uvicorn.run` are both replaced with
capture-only stand-ins."""

from __future__ import annotations

from palimpsest.cli import build_parser, cmd_serve


def _parse(extra_args: list[str]):
    parser = build_parser()
    return parser.parse_args(["serve", "--no-browser", *extra_args])


def _run_serve(extra_args: list[str], monkeypatch, tmp_path) -> dict:
    monkeypatch.chdir(tmp_path)
    captured: dict = {}

    def _fake_create_app(config, *, static_dir=None, extra_origins=frozenset(), **_kwargs):
        captured["static_dir"] = static_dir
        captured["extra_origins"] = extra_origins
        return object()

    import palimpsest.server.app as app_module

    monkeypatch.setattr(app_module, "create_app", _fake_create_app)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)

    args = _parse(extra_args)
    cmd_serve(args)
    return captured


def test_default_serve_mounts_the_packaged_static_dir(monkeypatch, tmp_path):
    captured = _run_serve([], monkeypatch, tmp_path)
    assert captured["static_dir"] is not None
    assert captured["extra_origins"] == frozenset()


def test_dev_skips_the_static_mount_and_allows_the_dev_origin(monkeypatch, tmp_path):
    captured = _run_serve(["--dev"], monkeypatch, tmp_path)
    assert captured["static_dir"] is None
    assert captured["extra_origins"] == frozenset({"http://localhost:5173"})


def test_api_only_skips_the_static_mount_without_folding_in_dev_origin(monkeypatch, tmp_path):
    captured = _run_serve(
        ["--api-only", "--allow-origin", "https://example.github.io"], monkeypatch, tmp_path
    )
    assert captured["static_dir"] is None
    # Only the explicit --allow-origin -- --dev-origin's default
    # (http://localhost:5173) must NOT sneak in just because --api-only
    # shares --dev's "no static mount" effect.
    assert captured["extra_origins"] == frozenset({"https://example.github.io"})


def test_api_only_with_no_allow_origin_allows_nothing_cross_origin(monkeypatch, tmp_path):
    captured = _run_serve(["--api-only"], monkeypatch, tmp_path)
    assert captured["extra_origins"] == frozenset()
