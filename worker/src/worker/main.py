"""Worker entrypoint. Long-polls dispatcher; processes one job at a time."""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import traceback
from pathlib import Path

from pitch_shared import Attachment, JobResult, JobStatus

from .config import Config
from .dispatcher_client import DispatcherClient
from .pipeline import FetchError, Pipeline, PipelineResult
from .tools import make_default_pipeline

log = logging.getLogger("pitch.worker")


async def process_one(client: DispatcherClient, pipeline: Pipeline, config: Config) -> bool:
    """Returns True if a job was processed (whether success or fail)."""
    job = await client.claim_next()
    if job is None:
        return False

    job_dir = config.work_dir / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    log.info("processing job=%s url=%s", job.id, job.url)

    try:
        await client.post_progress(job.id, JobStatus.fetching, "downloading")

        # The pipeline runs synchronously; we offload to a thread so we don't block
        # the loop. We can't easily ping progress mid-pipeline without restructuring,
        # so we kick off a background pinger that periodically taps the dispatcher
        # with the last-known stage.
        progress_state = {"status": JobStatus.fetching, "message": "downloading"}

        async def pinger():
            while True:
                await asyncio.sleep(15)
                try:
                    await client.post_progress(
                        job.id, progress_state["status"], progress_state["message"]
                    )
                except Exception:
                    pass

        pinger_task = asyncio.create_task(pinger())

        def progress_cb(status: JobStatus, message: str | None) -> None:
            progress_state["status"] = status
            progress_state["message"] = message or ""

        try:
            result = await asyncio.to_thread(
                _run_pipeline_with_progress,
                pipeline,
                job.url or "",
                job_dir,
                config.frame_every_seconds,
                progress_cb,
            )
        finally:
            pinger_task.cancel()
            try:
                await pinger_task
            except (asyncio.CancelledError, Exception):
                pass
        await client.post_result(
            job.id,
            JobResult(
                status=JobStatus.done,
                markdown=result.markdown,
                title=result.title,
                slug=result.slug,
                attachments=[
                    Attachment(filename=a.filename, base64=a.base64)
                    for a in result.attachments
                ],
            ),
        )
        log.info("done job=%s", job.id)
    except FetchError as e:
        log.warning("fetch_failed job=%s err=%s", job.id, e)
        await client.post_result(
            job.id,
            JobResult(
                status=JobStatus.failed,
                error=str(e),
                user_guidance=e.user_guidance,
            ),
        )
    except Exception as e:
        log.error("worker error job=%s\n%s", job.id, traceback.format_exc())
        await client.post_result(
            job.id,
            JobResult(
                status=JobStatus.failed,
                error=str(e),
                user_guidance="Worker error. Check the worker log on the Mac.",
            ),
        )
    finally:
        # Clean up job working files; keep dispatcher result.
        shutil.rmtree(job_dir, ignore_errors=True)
    return True


def _run_pipeline_with_progress(
    pipeline: Pipeline,
    url: str,
    job_dir: Path,
    frame_every_seconds: int,
    progress_cb,
) -> PipelineResult:
    """Sync wrapper that owns the heavy lifting."""
    return pipeline.run(
        url=url,
        work_dir=job_dir,
        frame_every_seconds=frame_every_seconds,
        progress_cb=progress_cb,
    )


async def run_forever(config: Config) -> None:
    client = DispatcherClient(config.dispatcher_url, config.worker_token)
    pipeline = make_default_pipeline(config)
    log.info("worker started; dispatcher=%s work_dir=%s", config.dispatcher_url, config.work_dir)
    while True:
        try:
            had_work = await process_one(client, pipeline, config)
        except Exception:
            log.exception("loop error; sleeping before retry")
            await asyncio.sleep(config.poll_idle_seconds)
            continue
        if not had_work:
            await asyncio.sleep(config.poll_idle_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        config = Config.from_env()
    except RuntimeError as e:
        print(f"config error: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        asyncio.run(run_forever(config))
    except KeyboardInterrupt:
        pass
