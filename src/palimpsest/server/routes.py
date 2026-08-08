"""API routes. See the module docstring in `app.py` for the security
model these all share (loopback-only, origin-checked, no auth)."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import os
from pathlib import Path

import fitz
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from palimpsest.config import loader as config_loader
from palimpsest.config.model import EntityGroups
from palimpsest.core import ir
from palimpsest.core import paths as core_paths
from palimpsest.pdf import layout as pdf_layout
from palimpsest.pdf import reflow
from palimpsest.qa.compare import render_page
from palimpsest.server.jobs import Job
from palimpsest.server.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    DocumentEstimateResponse,
    EntityGroupsResponse,
    EstimateRequest,
    HealthResponse,
    JobResponse,
    UploadResponse,
)
from palimpsest.server.uploads import UploadRejected, validate_and_save
from palimpsest.text.protect import EntityGuard
from palimpsest.translate.backend import TranslationContext
from palimpsest.translate.cache import Cache, compute_namespace
from palimpsest.translate.estimate import estimate_document

router = APIRouter(prefix="/api")

# The default DPI /pages/{n}.png renders at, and what _layout_envelope's
# px_width/px_height MUST be computed from -- the edit surface positions
# every overlay box as a percentage of these dimensions against the <img>
# it fetches from /pages/{n}.png with no dpi override, so the two have to
# describe the same raster or every box registers in the wrong place.
DEFAULT_PAGE_DPI = 110


def _state(request: Request):
    return request.app.state.palimpsest


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    from palimpsest import __version__

    state = _state(request)
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return HealthResponse(
        version=__version__,
        backend=state.config.backend.name,
        anthropic_key_present=bool(os.environ.get("ANTHROPIC_API_KEY")),
        gemini_key_present=bool(gemini_key),
    )


# -- entities -----------------------------------------------------------


@router.get("/entities", response_model=EntityGroupsResponse)
def get_entities(request: Request) -> EntityGroupsResponse:
    state = _state(request)
    groups = config_loader.load_entity_groups(state.config)
    return EntityGroupsResponse(
        companies=list(groups.companies), people=list(groups.people),
        places=list(groups.places), other=list(groups.other),
    )


@router.put("/entities", response_model=EntityGroupsResponse)
def put_entities(request: Request, body: EntityGroupsResponse) -> EntityGroupsResponse:
    state = _state(request)
    groups = EntityGroups(
        companies=tuple(body.companies), people=tuple(body.people),
        places=tuple(body.places), other=tuple(body.other),
    )
    path = state.entities_path
    config_loader.save_entity_groups(path, groups)
    # Reflected back so the caller sees exactly what was persisted --
    # this process's in-memory `state.entities` is refreshed too, so a
    # job submitted right after a PUT uses the new roster, not a stale
    # snapshot taken at server startup.
    state.refresh_entities()
    return body


# -- uploads --------------------------------------------------------------


@router.post("/uploads", response_model=UploadResponse)
async def upload(request: Request, file: UploadFile) -> UploadResponse:
    state = _state(request)
    content = await file.read()
    try:
        uploaded = validate_and_save(file.filename or "upload", content, state.uploads_dir)
    except UploadRejected as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state.remember_upload(uploaded)
    return UploadResponse(
        file_id=uploaded.file_id, name=uploaded.name, kind=str(uploaded.kind),
        pages=uploaded.pages, size=uploaded.size,
    )


def _cache_for(rel: str, state, backend) -> Cache:
    key = core_paths.cache_key(core_paths.norm_rel(rel))
    cache_path = state.config.paths.cache_dir / f"{key}.json"
    namespace = compute_namespace(
        backend.name, getattr(backend, "model", None),
        state.config.language.source, state.config.language.target,
        glossary_terms=state.glossary.terms, entities=state.entities,
    )
    return Cache(cache_path, namespace=namespace)


@router.post("/estimate", response_model=list[DocumentEstimateResponse])
def estimate(request: Request, body: EstimateRequest) -> list[DocumentEstimateResponse]:
    state = _state(request)
    backend = state.backend_factory(state.config)
    ctx = TranslationContext(
        source_lang=state.config.language.source, target_lang=state.config.language.target,
        entities=state.entities, glossary=state.glossary.terms,
    )
    results = []
    for file_id in body.file_ids:
        uploaded = state.get_upload(file_id)
        if uploaded is None:
            raise HTTPException(status_code=404, detail=f"unknown file_id {file_id!r}")

        if uploaded.kind == "office":
            from palimpsest.office import ooxml

            strings = ooxml.collect_strings(str(uploaded.path))
            names = [n for n in ooxml.sheet_names(str(uploaded.path)) if ooxml._translatable(n)]
            texts = strings + names
            kind, pages = None, None
        else:
            guard = EntityGuard(state.entities)
            scanned = uploaded.kind in ("scan", "ocr")
            min_size = (
                state.config.thresholds.min_text_size_scan
                if scanned else state.config.thresholds.min_text_size
            )
            doc = fitz.open(str(uploaded.path))
            texts = [
                p.text
                for pno in range(len(doc))
                for p in pdf_layout.extract_paragraphs(doc[pno], min_size=min_size)
                if not guard.skip(p.text)
            ]
            pages = len(doc)
            doc.close()
            kind = uploaded.kind

        cache = _cache_for(uploaded.name, state, backend)
        est = estimate_document(
            uploaded.name, texts, backend, ctx, cache, kind=kind, pages=pages
        )
        results.append(
            DocumentEstimateResponse(
                file_id=file_id, name=uploaded.name, kind=est.kind, pages=est.pages,
                unit_count=est.unit_count, unique_count=est.unique_count,
                cache_hits=est.cache_hits, input_tokens=est.corpus.input_tokens,
                output_tokens=est.corpus.output_tokens, usd=est.corpus.usd,
            )
        )
    return results


# -- jobs -------------------------------------------------------------------


@router.post("/jobs", response_model=CreateJobResponse)
def create_job(request: Request, body: CreateJobRequest) -> CreateJobResponse:
    state = _state(request)
    uploaded = []
    for file_id in body.file_ids:
        u = state.get_upload(file_id)
        if u is None:
            raise HTTPException(status_code=404, detail=f"unknown file_id {file_id!r}")
        uploaded.append(u)
    if not uploaded:
        raise HTTPException(status_code=400, detail="file_ids is empty")

    config = state.config
    if body.backend and body.backend != config.backend.name:
        config = dataclasses.replace(
            config, backend=dataclasses.replace(config.backend, name=body.backend)
        )
    backend = state.backend_factory(config)

    job = state.jobs.create(uploaded, backend_name=backend.name, dual=body.dual)
    uploaded_by_id = {u.file_id: u for u in uploaded}
    out_dir = state.jobs.jobs_dir / job.id
    state.jobs.submit(
        job, uploaded_by_id, config, backend, state.entities, state.glossary,
        state.post_rules, out_dir,
    )
    return CreateJobResponse(job_id=job.id)


def _get_job_or_404(state, job_id: str) -> Job:
    job = state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str) -> JobResponse:
    job = _get_job_or_404(_state(request), job_id)
    return JobResponse(**job.to_dict())


def _sse(data: dict) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode()


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str) -> StreamingResponse:
    state = _state(request)
    job = _get_job_or_404(state, job_id)

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, job._queue.get)
            if item is None:
                yield _sse({"type": "job-done", "status": job.status, "error": job.error})
                return
            yield _sse(
                {
                    "type": "progress",
                    "file_id": item.file_id,
                    "file_index": item.file_index,
                    "file_count": item.file_count,
                    "phase": item.event.phase,
                    "status": item.event.status,
                    "detail": item.event.detail,
                    "count": item.event.count,
                    "total": item.event.total,
                }
            )

    return StreamingResponse(stream(), media_type="text/event-stream")


def _job_file_or_404(job: Job, file_id: str | None):
    if file_id is None:
        if not job.files:
            raise HTTPException(status_code=404, detail="job has no files")
        return job.files[0]
    for jf in job.files:
        if jf.file_id == file_id:
            return jf
    raise HTTPException(status_code=404, detail=f"unknown file_id {file_id!r} for this job")


@router.get("/jobs/{job_id}/download/{artifact}")
def download(
    request: Request, job_id: str, artifact: str, file: str | None = Query(None)
) -> StreamingResponse:
    state = _state(request)
    job = _get_job_or_404(state, job_id)
    jf = _job_file_or_404(job, file)

    if artifact == "report":
        payload = json.dumps(jf.report or {}, indent=2).encode()
        report_name = f"{Path(jf.name).stem}.report.json"
        return StreamingResponse(
            io.BytesIO(payload), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{report_name}"'},
        )
    if artifact == "replica":
        path = jf.output_path
    elif artifact == "dual":
        path = jf.dual_path
    else:
        raise HTTPException(status_code=404, detail=f"unknown artifact {artifact!r}")

    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{artifact} not available for this file yet")
    return StreamingResponse(
        io.BytesIO(path.read_bytes()), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/jobs/{job_id}/pages/{page_no}.png")
def page_png(
    request: Request, job_id: str, page_no: int,
    side: str = Query("output"), file: str | None = Query(None), dpi: int = Query(DEFAULT_PAGE_DPI),
) -> StreamingResponse:
    state = _state(request)
    job = _get_job_or_404(state, job_id)
    jf = _job_file_or_404(job, file)

    if side == "source":
        uploaded = state.get_upload(jf.file_id)
        path = uploaded.path if uploaded else None
    elif side == "output":
        path = jf.output_path
    else:
        raise HTTPException(status_code=400, detail='side must be "source" or "output"')
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{side} page not available yet")

    image = render_page(path, page_no, dpi=dpi)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


def _layout_envelope(source_path: Path, source_name: str, pno: int) -> dict:
    """Same shape (and same code path) as `web/prototype/sample/generate.py`'s
    `build_layout_envelope` -- the browser's edit surface reads this
    without any reshaping, so the two must never diverge.

    `zoom`/`px_width`/`px_height` describe the SAME raster `/pages/{n}.png`
    (at its default DPI) actually returns -- see `DEFAULT_PAGE_DPI`'s
    docstring for why that agreement matters."""
    doc = fitz.open(str(source_path))
    try:
        page = doc[pno]
        paras = pdf_layout.extract_paragraphs(page, min_size=3.0)
        ir_page = pdf_layout.page_to_ir(page, paras)
        document = ir.Document(source=source_name, pages=(ir_page,))
        doc_dict = ir.to_dict(document)
        zoom = DEFAULT_PAGE_DPI / 72
        return {
            "schema": 1,
            "source": doc_dict["source"],
            "pages": doc_dict["pages"],
            "render": {
                "zoom": zoom,
                "pages": [
                    {
                        "number": pno,
                        "px_width": round(page.rect.width * zoom),
                        "px_height": round(page.rect.height * zoom),
                    }
                ],
            },
        }
    finally:
        doc.close()


@router.get("/jobs/{job_id}/layout")
def get_layout(
    request: Request, job_id: str, file: str | None = Query(None), page: int = Query(0)
) -> dict:
    state = _state(request)
    job = _get_job_or_404(state, job_id)
    jf = _job_file_or_404(job, file)
    if jf.kind == "office":
        raise HTTPException(status_code=400, detail="edit mode is not available for Office files")
    if jf.output_path is None or not jf.output_path.is_file():
        raise HTTPException(status_code=404, detail="translated output not available yet")
    return _layout_envelope(jf.output_path, jf.name, page)


@router.patch("/jobs/{job_id}/layout")
def patch_layout(
    request: Request, job_id: str, body: dict, file: str | None = Query(None)
) -> JSONResponse:
    """Persists edit-mode edits as JSON (an audit trail / recovery copy,
    kept regardless of reflow success) and regenerates the affected page
    of the translated PDF from them via `pdf.reflow.apply_page_edits`.

    The page to reflow comes from the payload itself
    (`document.pages[0].number`, matching `useEditBoxes.exportPayload`'s
    shape) rather than a query parameter, so the existing frontend call
    needs no changes to get real reflow."""
    state = _state(request)
    job = _get_job_or_404(state, job_id)
    jf = _job_file_or_404(job, file)
    if jf.kind == "office":
        raise HTTPException(status_code=400, detail="edit mode is not available for Office files")
    out_dir = state.jobs.jobs_dir / job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    edits_path = out_dir / f"{jf.file_id}.edits.json"
    edits_path.write_text(json.dumps(body, indent=2), encoding="utf-8")

    try:
        pages = body["document"]["pages"]
        page_body = pages[0]
        page_no = int(page_body.get("number", 0))
        paragraphs = page_body["paragraphs"]
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"malformed layout payload: {e}") from e

    if jf.output_path is None or not jf.output_path.is_file():
        raise HTTPException(status_code=404, detail="translated output not available yet")

    render_ctx = reflow.build_render_context(state.config, jf.name)
    try:
        result = reflow.apply_page_edits(jf.output_path, page_no, paragraphs, render_ctx)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not save reflowed page: {e}") from e

    return JSONResponse({**body, "reflow": result})
