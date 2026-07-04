from __future__ import annotations

from datetime import UTC, datetime, timedelta

from voice_toolbox.podcast.jobs import PodcastJobStore


def test_podcast_job_store_cancel_and_cleanup() -> None:
    store = PodcastJobStore(ttl_seconds=60, max_jobs=2)
    first = store.create(total_segments=3)

    cancelled = store.cancel(first.job_id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert store.is_cancelled(first.job_id) is True

    store.create()
    third = store.create()
    assert store.get(first.job_id) is None
    assert store.get(third.job_id) is not None


def test_podcast_job_store_keeps_active_jobs_when_trimming() -> None:
    store = PodcastJobStore(ttl_seconds=1, max_jobs=1)
    running = store.create()
    store.update(
        running.job_id,
        status="running",
        updated_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    queued = store.create()

    store.cleanup()

    assert store.get(running.job_id) is not None
    assert store.get(queued.job_id) is not None


def test_podcast_job_store_expires_old_jobs() -> None:
    store = PodcastJobStore(ttl_seconds=1, max_jobs=10)
    job = store.create()
    store.update(
        job.job_id,
        status="completed",
        updated_at=datetime.now(UTC) - timedelta(seconds=5),
    )

    store.cleanup()

    assert store.get(job.job_id) is None
