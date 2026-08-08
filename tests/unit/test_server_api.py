"""Full HTTP-level server tests: upload -> estimate -> job -> SSE ->
download, over `fastapi.testclient.TestClient`, a `FakeBackend` (see
`tests/fixtures/fake_backend.py`), and a synthetic PDF (see
`tests/fixtures/synth.py`) -- no network call and no API key anywhere
in this file, matching every other test in this project.
"""

from __future__ import annotations

import json
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


def _fake_backend_factory(_config):
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
