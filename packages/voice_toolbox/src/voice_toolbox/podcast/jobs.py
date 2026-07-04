from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from voice_toolbox.models import AudioArtifact

PodcastJobState = Literal["queued", "running", "completed", "failed", "cancelled"]
ACTIVE_JOB_STATUSES: set[PodcastJobState] = {"queued", "running"}


class PodcastJobStoreError(RuntimeError):
    pass


class PodcastFailedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    speaker: str


class PodcastJobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: PodcastJobState
    current_segment: int = 0
    total_segments: int = 0
    current_speaker: str | None = None
    current_text_preview: str | None = None
    artifact: AudioArtifact | None = None
    error_summary: str | None = None
    failed_segment: PodcastFailedSegment | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PodcastJobStore:
    def __init__(self, *, ttl_seconds: int = 3600, max_jobs: int = 100) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self.max_jobs = max_jobs
        self._jobs: dict[str, PodcastJobStatus] = {}
        self._cancelled: set[str] = set()
        self._lock = RLock()

    def create(self, *, total_segments: int = 0) -> PodcastJobStatus:
        with self._lock:
            self.cleanup()
            active_count = sum(
                1 for job in self._jobs.values() if job.status in ACTIVE_JOB_STATUSES
            )
            if active_count >= self.max_jobs:
                raise PodcastJobStoreError("too many active podcast jobs")
            job = PodcastJobStatus(
                job_id=f"podcast-{uuid4().hex}",
                status="queued",
                total_segments=total_segments,
            )
            self._jobs[job.job_id] = job
            self._trim_locked()
            return job

    def get(self, job_id: str) -> PodcastJobStatus | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: object) -> PodcastJobStatus:
        with self._lock:
            current = self._jobs[job_id]
            timestamp = changes.pop("updated_at", datetime.now(UTC))
            updated = current.model_copy(update={**changes, "updated_at": timestamp})
            self._jobs[job_id] = updated
            return updated

    def cancel(self, job_id: str) -> PodcastJobStatus | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            self._cancelled.add(job_id)
            if job.status == "queued":
                job = job.model_copy(
                    update={"status": "cancelled", "updated_at": datetime.now(UTC)}
                )
                self._jobs[job_id] = job
            return job

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def cleanup(self) -> None:
        with self._lock:
            now = datetime.now(UTC)
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status not in ACTIVE_JOB_STATUSES and now - job.updated_at > self.ttl
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
                self._cancelled.discard(job_id)
            self._trim_locked()

    def _trim_locked(self) -> None:
        while len(self._jobs) > self.max_jobs:
            terminal_jobs = [
                job for job in self._jobs.values() if job.status not in ACTIVE_JOB_STATUSES
            ]
            if not terminal_jobs:
                break
            oldest = min(terminal_jobs, key=lambda job: job.updated_at)
            self._jobs.pop(oldest.job_id, None)
            self._cancelled.discard(oldest.job_id)
