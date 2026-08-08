"""In-process job registry and single-worker execution.

One `ThreadPoolExecutor(max_workers=1)` for the whole process, not one
per job and not a process pool. The pipeline is blocking, CPU-bound
PyMuPDF work -- it must run off the asyncio event loop, but a local,
single-user tool has no reason to translate two documents at once (it
would just make both slower on typical hardware) and a single worker
keeps the machine responsive for whatever else the user is doing. No
Celery/Redis: that's infrastructure for a multi-worker hosted service,
the wrong weight entirely for one person's laptop.

Progress delivery: the worker thread calls the `progress` callback
synchronously from inside `translate_pdf_document`/
`translate_office_document` (see `core.progress`). Each call does a
plain `queue.Queue.put` -- thread-safe, and cheap enough to call from a
tight per-chunk loop. The SSE route drains that queue from the asyncio
side via `loop.run_in_executor`, so a blocking `queue.get()` never
stalls the event loop the rest of the app depends on.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from palimpsest.config.model import Config
from palimpsest.core.progress import ProgressEvent
from palimpsest.office.pipeline import translate_office_document
from palimpsest.pdf.classify import Kind
from palimpsest.pdf.pipeline import translate_pdf_document
from palimpsest.qa.compare import build_dual_pdf
from palimpsest.server.uploads import UploadedFile
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import Backend

log = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "failed"]
FileStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class JobFileEvent:
    """A progress event tagged with which file (and which position in
    the job's file list) it came from -- the piece `ProgressEvent` alone
    can't carry, since the pipeline that emits it knows nothing about
    the job wrapping it."""

    file_id: str
    file_index: int
    file_count: int
    event: ProgressEvent


@dataclass
class JobFile:
    file_id: str
    name: str
    kind: str
    status: FileStatus = "pending"
    report: dict | None = None
    error: str | None = None
    output_path: Path | None = None
    dual_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id, "name": self.name, "kind": self.kind,
            "status": self.status, "report": self.report, "error": self.error,
        }


@dataclass
class Job:
    id: str
    files: list[JobFile]
    backend_name: str
    dual: bool
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    _queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "backend": self.backend_name,
                "created_at": self.created_at,
                "error": self.error,
                "files": [f.to_dict() for f in self.files],
            }


class JobRegistry:
    """One registry per running server process. Job records also mirror
    to a JSON file per job under `jobs_dir`, so a finished job's report
    survives a server restart even though in-flight progress does not
    (there is no "resume a job" story here -- see the plan's explicit
    non-goals)."""

    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="palimpsest-job")

    def create(
        self, uploaded: list[UploadedFile], backend_name: str, dual: bool
    ) -> Job:
        job_id = uuid.uuid4().hex
        files = [JobFile(file_id=u.file_id, name=u.name, kind=str(u.kind)) for u in uploaded]
        job = Job(id=job_id, files=files, backend_name=backend_name, dual=dual)
        self._jobs[job_id] = job
        self._persist(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def submit(
        self,
        job: Job,
        uploaded_by_id: dict[str, UploadedFile],
        config: Config,
        backend: Backend,
        entities: tuple[str, ...],
        glossary: Glossary,
        post_rules: tuple[tuple[str, str], ...],
        out_dir: Path,
    ) -> None:
        self._executor.submit(
            self._run, job, uploaded_by_id, config, backend, entities, glossary, post_rules, out_dir
        )

    def _persist(self, job: Job) -> None:
        try:
            (self.jobs_dir / f"{job.id}.json").write_text(
                json.dumps(job.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError:
            log.warning("could not persist job %s", job.id, exc_info=True)

    def _run(
        self,
        job: Job,
        uploaded_by_id: dict[str, UploadedFile],
        config: Config,
        backend: Backend,
        entities: tuple[str, ...],
        glossary: Glossary,
        post_rules: tuple[tuple[str, str], ...],
        out_dir: Path,
    ) -> None:
        with job._lock:
            job.status = "running"
        self._persist(job)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_count = len(job.files)

        try:
            for index, jf in enumerate(job.files):
                uploaded = uploaded_by_id[jf.file_id]
                with job._lock:
                    jf.status = "running"
                self._persist(job)

                def progress(event: ProgressEvent, jf=jf, index=index) -> None:
                    job._queue.put(
                        JobFileEvent(
                            file_id=jf.file_id, file_index=index,
                            file_count=file_count, event=event,
                        )
                    )

                rel = jf.name
                out_path = out_dir / f"{jf.file_id}.{Path(jf.name).suffix.lstrip('.')}"
                try:
                    if uploaded.kind == "office":
                        report = translate_office_document(
                            uploaded.path, out_path, rel, backend,
                            entities, glossary, post_rules, config,
                        )
                    else:
                        # uploads.validate_and_save only ever assigns a
                        # non-Kind string for the "office" case, already
                        # excluded above -- everything else is a real Kind.
                        report = translate_pdf_document(
                            uploaded.path, out_path, rel, backend,
                            entities, glossary, post_rules, config,
                            kind=cast(Kind, uploaded.kind), progress=progress,
                        )
                    with job._lock:
                        jf.status = "done"
                        jf.report = report
                        jf.output_path = out_path
                    if job.dual and uploaded.kind != "office":
                        dual_path = out_dir / f"{jf.file_id}.dual.pdf"
                        build_dual_pdf(uploaded.path, out_path, dual_path)
                        with job._lock:
                            jf.dual_path = dual_path
                except Exception as e:  # noqa: BLE001 -- reported per-file, job continues
                    log.exception("job %s: file %s failed", job.id, jf.file_id)
                    with job._lock:
                        jf.status = "failed"
                        jf.error = str(e)
                self._persist(job)

            with job._lock:
                job.status = "failed" if any(f.status == "failed" for f in job.files) else "done"
        except Exception as e:  # noqa: BLE001 -- job-level failure, surfaced to the client
            log.exception("job %s failed", job.id)
            with job._lock:
                job.status = "failed"
                job.error = str(e)
        finally:
            self._persist(job)
            job._queue.put(None)  # sentinel: SSE stream ends
