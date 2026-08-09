"""Unit tests for `JobRegistry` persistence -- a fresh `JobRegistry`
pointed at the same `jobs_dir` is exactly what happens on a server
restart, since nothing else stores job state."""

from __future__ import annotations

from palimpsest.server.jobs import JobRegistry
from palimpsest.server.uploads import UploadedFile


def _uploaded_file(tmp_path, file_id="f1", name="doc.pdf") -> UploadedFile:
    path = tmp_path / f"{file_id}.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake\n")
    return UploadedFile(
        file_id=file_id, name=name, kind="digital", pages=1, size=path.stat().st_size, path=path
    )


def test_finished_job_survives_restart(tmp_path):
    jobs_dir = tmp_path / "jobs"
    registry = JobRegistry(jobs_dir)
    job = registry.create([_uploaded_file(tmp_path)], backend_name="google", dual=False)
    output_path = tmp_path / "out.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%out\n")
    jf = job.files[0]
    jf.status = "done"
    jf.report = {"pages": 1, "translated": 1}
    jf.output_path = output_path
    job.status = "done"
    registry._persist(job)

    restarted = JobRegistry(jobs_dir)
    restored = restarted.get(job.id)
    assert restored is not None
    assert restored.status == "done"
    assert restored.files[0].status == "done"
    assert restored.files[0].report == {"pages": 1, "translated": 1}
    assert restored.files[0].output_path == output_path
    # A client subscribing to SSE for an already-finished, restored job
    # must not hang forever waiting on a queue no worker will ever fill.
    assert restored._queue.get_nowait() is None


def test_in_flight_job_is_marked_failed_on_restart(tmp_path):
    jobs_dir = tmp_path / "jobs"
    registry = JobRegistry(jobs_dir)
    job = registry.create([_uploaded_file(tmp_path)], backend_name="google", dual=False)
    job.status = "running"
    job.files[0].status = "running"
    registry._persist(job)

    restarted = JobRegistry(jobs_dir)
    restored = restarted.get(job.id)
    assert restored is not None
    assert restored.status == "failed"
    assert restored.files[0].status == "failed"
    assert restored.error
    assert restored.files[0].error


def test_malformed_job_record_is_skipped_not_fatal(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "bad.json").write_text("{not valid json", encoding="utf-8")
    (jobs_dir / "incomplete.json").write_text("{}", encoding="utf-8")

    registry = JobRegistry(jobs_dir)
    assert registry.get("bad") is None
    assert registry.get("incomplete") is None


# -- active_count_for: the one-job-per-visitor guardrail --------------------


def test_active_count_for_counts_only_queued_and_running(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    a1 = registry.create(
        [_uploaded_file(tmp_path, file_id="f1")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    registry.create(
        [_uploaded_file(tmp_path, file_id="f2")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    done = registry.create(
        [_uploaded_file(tmp_path, file_id="f3")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    done.status = "done"

    assert registry.active_count_for("visitor-a") == 2  # a1 and the second, both "queued"
    assert registry.active_count_for("visitor-b") == 0
    a1.status = "failed"
    assert registry.active_count_for("visitor-a") == 1


def test_active_count_for_is_scoped_per_visitor(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    registry.create(
        [_uploaded_file(tmp_path, file_id="f1")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    registry.create(
        [_uploaded_file(tmp_path, file_id="f2")], backend_name="google", dual=False,
        visitor_id="visitor-b",
    )
    assert registry.active_count_for("visitor-a") == 1
    assert registry.active_count_for("visitor-b") == 1
    assert registry.active_count_for("local") == 0


# -- cancel: frees a visitor's quota slot without a real interruption -------


def test_active_jobs_for_returns_the_actual_job_objects(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    a1 = registry.create(
        [_uploaded_file(tmp_path, file_id="f1")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    done = registry.create(
        [_uploaded_file(tmp_path, file_id="f2")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    done.status = "done"

    active = registry.active_jobs_for("visitor-a")
    assert [j.id for j in active] == [a1.id]
    assert registry.active_jobs_for("visitor-b") == []


def test_cancel_sets_status_and_frees_active_count(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    job = registry.create(
        [_uploaded_file(tmp_path, file_id="f1")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    assert registry.active_count_for("visitor-a") == 1

    cancelled = registry.cancel(job.id, "visitor-a")
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.error
    assert registry.active_count_for("visitor-a") == 0


def test_cancel_unknown_job_returns_none(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    assert registry.cancel("does-not-exist", "visitor-a") is None


def test_cancel_wrong_visitor_returns_none(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    job = registry.create(
        [_uploaded_file(tmp_path, file_id="f1")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    assert registry.cancel(job.id, "visitor-b") is None
    # Not cancelled -- the wrong-visitor call must be a complete no-op.
    assert registry.get(job.id).status == "queued"


def test_cancel_an_already_terminal_job_is_a_harmless_no_op(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    job = registry.create(
        [_uploaded_file(tmp_path, file_id="f1")], backend_name="google", dual=False,
        visitor_id="visitor-a",
    )
    job.status = "done"

    result = registry.cancel(job.id, "visitor-a")
    assert result is not None
    assert result.status == "done"  # left as-is, not overwritten to "cancelled"
