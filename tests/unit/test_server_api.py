"""Full HTTP-level server tests: upload -> estimate -> job -> SSE ->
download, over `fastapi.testclient.TestClient`, a `FakeBackend` (see
`tests/fixtures/fake_backend.py`), and a synthetic PDF (see
`tests/fixtures/synth.py`) -- no network call and no API key anywhere
in this file, matching every other test in this project.
"""

from __future__ import annotations

import json
import os
import time

import fitz
import pytest
from fastapi.testclient import TestClient

from palimpsest.config.model import Config, FontsConfig, PathsConfig, ThresholdsConfig
from palimpsest.office.render import find_soffice
from palimpsest.server.app import create_app
from tests.fixtures.fake_backend import FakeBackend
from tests.fixtures.office_docs import docx_bytes


def _config(tmp_path) -> Config:
    return Config(
        paths=PathsConfig(
            work_dir=tmp_path / "work", cache_dir=tmp_path / "cache",
            report_dir=tmp_path / "reports",
        ),
        thresholds=ThresholdsConfig(),
        fonts=FontsConfig(use_bundled_fallback=True),
    )


def _fake_backend_factory(_config, **_kwargs):
    return FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)


@pytest.fixture
def client(tmp_path):
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        yield c


def _pdf_bytes(text: str = "Hola mundo, este es un documento de prueba.") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(fitz.Rect(40, 40, 360, 160), text, fontsize=12, fontname="helv", align=0)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client, name="doc.pdf", content=None) -> dict:
    content = content or _pdf_bytes()
    resp = client.post("/api/uploads", files={"file": (name, content, "application/pdf")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _wait_for_job(client, job_id, timeout=10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# -- health ------------------------------------------------------------


def test_health(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anthropic_key_present"] is False
    assert body["gemini_key_present"] is False
    assert "backend" in body and "version" in body


# -- per-visitor key isolation --------------------------------------------
#
# Every request in this file until now carried no X-Palimpsest-Visitor
# header, so it landed in the local sentinel bucket (routes.py's
# _LOCAL_VISITOR) -- unchanged behavior, covered above. These exercise
# what's new: two DIFFERENT visitor ids must never see each other's keys.


def test_health_key_presence_is_scoped_per_visitor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        c.put(
            "/api/keys", json={"anthropic_api_key": "sk-ant-visitor-a-key"},
            headers={"X-Palimpsest-Visitor": "visitor-a"},
        )
        resp_a = c.get("/api/health", headers={"X-Palimpsest-Visitor": "visitor-a"})
        resp_b = c.get("/api/health", headers={"X-Palimpsest-Visitor": "visitor-b"})
    assert resp_a.json()["anthropic_key_present"] is True
    assert resp_b.json()["anthropic_key_present"] is False
    # Never lands in the operator's own environment or .env -- only the
    # local sentinel's key does (see test_put_keys_sets_env_and_persists_to_dotenv).
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_two_visitors_keys_never_cross(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        c.put(
            "/api/keys", json={"gemini_api_key": "visitor-a-gemini-key"},
            headers={"X-Palimpsest-Visitor": "visitor-a"},
        )
        c.put(
            "/api/keys", json={"gemini_api_key": "visitor-b-gemini-key"},
            headers={"X-Palimpsest-Visitor": "visitor-b"},
        )
        resp_a = c.get("/api/health", headers={"X-Palimpsest-Visitor": "visitor-a"})
        resp_b = c.get("/api/health", headers={"X-Palimpsest-Visitor": "visitor-b"})
    assert resp_a.json()["gemini_key_present"] is True
    assert resp_b.json()["gemini_key_present"] is True
    app_state = app.state.palimpsest
    assert app_state.get_keys("visitor-a")["GEMINI_API_KEY"] == "visitor-a-gemini-key"
    assert app_state.get_keys("visitor-b")["GEMINI_API_KEY"] == "visitor-b-gemini-key"


def test_visitor_header_beats_query_param_fallback(tmp_path, monkeypatch):
    """SSE/download/page URLs can't set headers, so they pass `?visitor=`
    instead (see api.js) -- confirm the header wins when both are present
    (a fetch() call always sends both getApiBase() and the header; the
    query param exists only for the handful of call sites that can't)."""
    monkeypatch.chdir(tmp_path)
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        c.put(
            "/api/keys", json={"gemini_api_key": "header-visitor-key"},
            headers={"X-Palimpsest-Visitor": "header-visitor"},
        )
        resp = c.get(
            "/api/health?visitor=query-visitor", headers={"X-Palimpsest-Visitor": "header-visitor"}
        )
    assert resp.json()["gemini_key_present"] is True


# -- the security-critical case: no silent fallback to the operator's key --
#
# routes.py's _resolve_key()/registry.make_backend's allow_env_fallback
# exist specifically so a real remote visitor with no key of their own
# can never end up using whatever key the SERVER PROCESS happens to have
# in its own environment (see app.py's module docstring). This uses the
# REAL translate.registry.make_backend as backend_factory -- not the
# FakeBackend every other test in this file uses -- because the fake
# bypasses key resolution entirely and so can't exercise this at all.


def test_non_local_visitor_with_no_key_gets_a_clean_error_not_the_operators_key(
    tmp_path, monkeypatch
):
    pytest.importorskip("anthropic")
    from palimpsest.config.model import BackendConfig
    from palimpsest.translate.registry import make_backend as real_make_backend

    monkeypatch.chdir(tmp_path)
    # The operator's own real credential -- exactly what a hosted
    # deployment's process environment would have for the local sentinel.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-the-operators-own-real-key")
    config = _config(tmp_path)
    config = Config(
        paths=config.paths, thresholds=config.thresholds, fonts=config.fonts,
        backend=BackendConfig(name="anthropic", fallback=None),
    )
    app = create_app(config, backend_factory=real_make_backend)
    with TestClient(app) as c:
        resp = c.post(
            "/api/estimate", json={"file_ids": []},
            headers={"X-Palimpsest-Visitor": "a-stranger-with-no-key"},
        )
    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"].lower() or "key" in resp.json()["detail"].lower()


def test_local_sentinel_still_uses_the_env_key_unchanged(tmp_path, monkeypatch):
    """Same setup as above, minus the visitor header -- the classic
    single-user desktop workflow must be completely unaffected: the
    local sentinel's own env key is still used, not refused."""
    pytest.importorskip("anthropic")
    import palimpsest.translate.anthropic as anthropic_backend
    from tests.fixtures.fake_anthropic_client import FakeAnthropicClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-the-operators-own-real-key")
    monkeypatch.setattr(
        anthropic_backend.anthropic, "Anthropic", lambda **_kwargs: FakeAnthropicClient()
    )
    from palimpsest.config.model import BackendConfig
    from palimpsest.translate.registry import make_backend as real_make_backend

    config = _config(tmp_path)
    config = Config(
        paths=config.paths, thresholds=config.thresholds, fonts=config.fonts,
        backend=BackendConfig(name="anthropic", fallback=None),
    )
    app = create_app(config, backend_factory=real_make_backend)
    with TestClient(app) as c:
        resp = c.post("/api/estimate", json={"file_ids": []})  # no visitor header at all
    assert resp.status_code == 200


# -- entities ------------------------------------------------------------


def test_entities_round_trip(client):
    resp = client.get("/api/entities")
    assert resp.status_code == 200
    assert resp.json() == {"companies": [], "people": [], "places": [], "other": []}

    body = {
        "companies": ["Grupo Meridian"], "people": ["Andres Carreno"],
        "places": [], "other": [],
    }
    put_resp = client.put("/api/entities", json=body)
    assert put_resp.status_code == 200
    assert put_resp.json() == body

    get_resp = client.get("/api/entities")
    assert get_resp.json() == body


# -- uploads ------------------------------------------------------------


def test_upload_accepts_pdf(client):
    data = _upload(client)
    assert data["kind"] in ("digital", "scan", "ocr")
    assert data["pages"] == 1
    assert data["size"] > 0
    assert data["file_id"]


def test_upload_rejects_bad_extension(client):
    resp = client.post(
        "/api/uploads", files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")}
    )
    assert resp.status_code == 400
    assert "unsupported file type" in resp.json()["detail"]


def test_upload_rejects_renamed_exe(client):
    resp = client.post(
        "/api/uploads",
        files={"file": ("fake.pdf", b"MZ\x90\x00\x03\x00\x00\x00", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "does not match" in resp.json()["detail"]


def test_upload_rejects_traversal_filename(client):
    resp = client.post(
        "/api/uploads",
        files={"file": ("../../etc/passwd.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert resp.status_code == 400


# -- estimate ------------------------------------------------------------


def test_estimate_unknown_file_id_404(client):
    resp = client.post("/api/estimate", json={"file_ids": ["nope"]})
    assert resp.status_code == 404


def test_estimate_returns_document_numbers(client):
    uploaded = _upload(client)
    resp = client.post("/api/estimate", json={"file_ids": [uploaded["file_id"]]})
    assert resp.status_code == 200
    [est] = resp.json()
    assert est["file_id"] == uploaded["file_id"]
    assert est["unique_count"] >= 1
    assert est["cache_hits"] == 0  # fresh cache, nothing warmed yet


# -- jobs: create, progress, download ------------------------------------


def test_job_unknown_file_id_404(client):
    resp = client.post("/api/jobs", json={"file_ids": ["nope"]})
    assert resp.status_code == 404


def test_job_empty_file_ids_400(client):
    resp = client.post("/api/jobs", json={"file_ids": []})
    assert resp.status_code == 400


def test_full_job_lifecycle_translates_and_downloads(client):
    uploaded = _upload(client)
    create_resp = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]], "dual": True})
    assert create_resp.status_code == 200
    job_id = create_resp.json()["job_id"]

    job = _wait_for_job(client, job_id)
    assert job["status"] == "done", job
    [jf] = job["files"]
    assert jf["status"] == "done"
    assert jf["report"]["translated"] >= 1

    replica = client.get(f"/api/jobs/{job_id}/download/replica")
    assert replica.status_code == 200
    assert replica.content.startswith(b"%PDF")

    dual = client.get(f"/api/jobs/{job_id}/download/dual")
    assert dual.status_code == 200
    assert dual.content.startswith(b"%PDF")

    report = client.get(f"/api/jobs/{job_id}/download/report")
    assert report.status_code == 200
    report_body = json.loads(report.content)
    assert report_body["translated"] >= 1


def test_download_unknown_artifact_404(client):
    uploaded = _upload(client)
    job_id = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]]}).json()["job_id"]
    _wait_for_job(client, job_id)
    resp = client.get(f"/api/jobs/{job_id}/download/nonsense")
    assert resp.status_code == 404


def test_download_before_job_finishes_is_404_not_a_crash(client):
    uploaded = _upload(client)
    job_id = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]]}).json()["job_id"]
    resp = client.get(f"/api/jobs/{job_id}/download/replica")
    assert resp.status_code in (404, 200)  # 200 only if the (fast) job already finished


def test_get_job_unknown_id_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


# -- SSE progress ------------------------------------------------------


def test_job_events_stream_reports_all_six_phases(client):
    uploaded = _upload(client)
    job_id = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]]}).json()["job_id"]

    phases_seen = set()
    saw_job_done = False
    with client.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[len("data: "):])
            if payload["type"] == "job-done":
                saw_job_done = True
                assert payload["status"] == "done"
                break
            phases_seen.add(payload["phase"])

    assert saw_job_done
    for phase in ("classify", "ocr", "extract", "translate", "render", "save"):
        assert phase in phases_seen


# -- pages / layout ------------------------------------------------------


def test_page_png_and_layout_after_job_completes(client):
    uploaded = _upload(client)
    job_id = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]]}).json()["job_id"]
    _wait_for_job(client, job_id)

    png_resp = client.get(f"/api/jobs/{job_id}/pages/0.png")
    assert png_resp.status_code == 200
    assert png_resp.content.startswith(b"\x89PNG")

    layout_resp = client.get(f"/api/jobs/{job_id}/layout")
    assert layout_resp.status_code == 200
    envelope = layout_resp.json()
    assert envelope["schema"] == 1
    assert len(envelope["pages"]) == 1
    assert envelope["pages"][0]["paragraphs"]

    page = envelope["pages"][0]
    para0 = page["paragraphs"][0]
    edited = {
        **para0, "edit": "modified",
        "runs": [{"text": "Reflowed replacement text", "bold": False, "italic": False,
                   "underline": True, "highlight": None, "color": para0["color"]}],
    }
    patch_body = {
        "schema": 1, "job": job_id,
        "document": {
            "source": envelope["source"],
            "pages": [{"number": 0, "width": page["width"], "height": page["height"],
                       "paragraphs": [edited]}],
        },
    }
    patch_resp = client.patch(f"/api/jobs/{job_id}/layout", json=patch_body)
    assert patch_resp.status_code == 200, patch_resp.text
    reflow_result = patch_resp.json()["reflow"]
    assert reflow_result["page"] == 0
    assert reflow_result["redrawn"] >= 1

    # The edit must land in the actual PDF, not just the draft sidecar.
    download_resp = client.get(f"/api/jobs/{job_id}/download/replica")
    assert download_resp.status_code == 200
    doc = fitz.open(stream=download_resp.content, filetype="pdf")
    try:
        assert "Reflowed replacement" in doc[0].get_text()
    finally:
        doc.close()


def test_patch_layout_rejects_malformed_payload(client):
    uploaded = _upload(client)
    job_id = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]]}).json()["job_id"]
    _wait_for_job(client, job_id)

    resp = client.patch(f"/api/jobs/{job_id}/layout", json={"note": "not a layout envelope"})
    assert resp.status_code == 400


# -- office file preview --------------------------------------------------


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _office_job(client) -> tuple[str, str]:
    resp = client.post(
        "/api/uploads", files={"file": ("doc.docx", docx_bytes(), _DOCX_MIME)}
    )
    assert resp.status_code == 200, resp.text
    uploaded = resp.json()
    assert uploaded["kind"] == "office"
    job_id = client.post("/api/jobs", json={"file_ids": [uploaded["file_id"]]}).json()["job_id"]
    _wait_for_job(client, job_id)
    return job_id, uploaded["file_id"]


def test_office_edit_mode_is_rejected(client):
    job_id, _ = _office_job(client)
    resp = client.get(f"/api/jobs/{job_id}/layout")
    assert resp.status_code == 400
    assert "Office" in resp.json()["detail"]

    patch_resp = client.patch(f"/api/jobs/{job_id}/layout", json={"document": {"pages": []}})
    assert patch_resp.status_code == 400


def test_office_page_preview_returns_503_when_libreoffice_missing(client, monkeypatch):
    from palimpsest.server import routes

    monkeypatch.setattr(routes.office_render, "find_soffice", lambda: None)
    job_id, _ = _office_job(client)
    resp = client.get(f"/api/jobs/{job_id}/pages/0.png?side=source")
    assert resp.status_code == 503
    assert "LibreOffice" in resp.json()["detail"]


@pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed on this machine")
def test_office_page_preview_renders_a_real_page(client):
    job_id, _ = _office_job(client)
    resp = client.get(f"/api/jobs/{job_id}/pages/0.png?side=source")
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"\x89PNG")


# -- origin check middleware ---------------------------------------------


def test_cross_origin_mutating_request_is_rejected(client):
    resp = client.put(
        "/api/entities",
        json={"companies": [], "people": [], "places": [], "other": []},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


def test_same_origin_request_with_no_origin_header_is_allowed(client):
    # TestClient sends no Origin header by default -- the common case
    # for a same-origin fetch/XHR is that browsers DO send one, but a
    # plain top-level navigation does not, and neither should be blocked.
    resp = client.put(
        "/api/entities", json={"companies": [], "people": [], "places": [], "other": []},
    )
    assert resp.status_code == 200


def test_same_origin_request_with_origin_header_is_allowed(client):
    # Regression test: fetch/XHR from the served SPA itself DOES set an
    # Origin header even for a same-origin request (browsers never let a
    # page suppress it) -- an earlier version of OriginCheckMiddleware
    # only ever allowed `--dev`'s explicit dev_origin, so this exact
    # request (the shape every real upload/job/entities/layout call from
    # the built app makes) was rejected with 403 in production mode.
    resp = client.put(
        "/api/entities",
        json={"companies": [], "people": [], "places": [], "other": []},
        headers={"Origin": str(client.base_url)},
    )
    assert resp.status_code == 200


def test_allow_origin_permits_an_explicitly_allowlisted_cross_origin_request(tmp_path):
    config = _config(tmp_path)
    app = create_app(
        config, backend_factory=_fake_backend_factory,
        extra_origins=frozenset({"https://example.github.io"}),
    )
    with TestClient(app) as c:
        resp = c.put(
            "/api/entities",
            json={"companies": [], "people": [], "places": [], "other": []},
            headers={"Origin": "https://example.github.io"},
        )
    assert resp.status_code == 200


def test_allow_origin_still_rejects_any_other_cross_origin_request(tmp_path):
    config = _config(tmp_path)
    app = create_app(
        config, backend_factory=_fake_backend_factory,
        extra_origins=frozenset({"https://example.github.io"}),
    )
    with TestClient(app) as c:
        resp = c.put(
            "/api/entities",
            json={"companies": [], "people": [], "places": [], "other": []},
            headers={"Origin": "https://evil.example"},
        )
    assert resp.status_code == 403


def test_private_network_access_preflight_succeeds_when_allowlisted(tmp_path):
    # Status code matters as much as the header: Starlette's CORSMiddleware
    # treats a preflight carrying Access-Control-Request-Private-Network as
    # a FAILURE (400 "Disallowed CORS private-network") unless
    # allow_private_network=True is passed to it -- a real browser reading
    # this response cares about the 2xx status just as much as the header,
    # so a test that only checks the header can pass while the preflight
    # is still actually rejected. Confirmed with a real curl preflight
    # against a running server before trusting this assertion.
    config = _config(tmp_path)
    app = create_app(
        config, backend_factory=_fake_backend_factory,
        extra_origins=frozenset({"https://example.github.io"}),
    )
    with TestClient(app) as c:
        resp = c.options(
            "/api/entities",
            headers={
                "Origin": "https://example.github.io",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Private-Network": "true",
            },
        )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-private-network") == "true"


def test_no_extra_origins_means_no_cors_headers_at_all(client):
    # Plain `palimpsest serve` (no --dev, no --allow-origin) must be
    # byte-for-byte unchanged: no CORSMiddleware, no PNA header, ever.
    resp = client.options(
        "/api/entities",
        headers={
            "Origin": "https://example.github.io",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert "access-control-allow-private-network" not in resp.headers
    assert "access-control-allow-origin" not in resp.headers


# -- PUT /api/keys --------------------------------------------------------


def test_put_keys_sets_env_and_persists_to_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # find_dotenv() must never touch the real repo .env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        resp = c.put("/api/keys", json={"anthropic_api_key": "sk-ant-test123"})
    assert resp.status_code == 200
    assert resp.json()["anthropic_key_present"] is True
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test123"
    dotenv_path = app.state.palimpsest.dotenv_path
    assert "sk-ant-test123" in dotenv_path.read_text(encoding="utf-8")


def test_put_keys_never_echoes_the_raw_value_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        resp = c.put("/api/keys", json={"anthropic_api_key": "sk-ant-super-secret"})
    assert "sk-ant-super-secret" not in resp.text


def test_put_keys_empty_field_is_a_noop_not_a_clear(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "already-set-by-shell")
    config = _config(tmp_path)
    app = create_app(config, backend_factory=_fake_backend_factory)
    with TestClient(app) as c:
        resp = c.put("/api/keys", json={"gemini_api_key": "new-gemini-key"})
    assert resp.status_code == 200
    assert os.environ["ANTHROPIC_API_KEY"] == "already-set-by-shell"
    assert resp.json()["anthropic_key_present"] is True
    assert resp.json()["gemini_key_present"] is True
