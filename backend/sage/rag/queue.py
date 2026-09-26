"""
SAGE RAG Indexing Queue — manages async document indexing as a background service.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("sage.rag.queue")

@dataclass
class IndexingJob:
    """A single unit of work for the indexing queue."""
    file_path: str
    workspace_id: str
    document_id: Optional[str] = None
    reindex: bool = False

class IndexingQueue:
    def __init__(self, max_queue_size: int = 100):
        self._queue: asyncio.Queue[Optional[IndexingJob]] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the background worker. Call once during app startup."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("RAG indexing queue started")

    async def stop(self):
        """Gracefully stop the worker. Call during app shutdown."""
        if not self._running:
            return
        self._running = False
        await self._queue.put(None)
        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=30.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
                logger.warning("RAG indexing worker did not stop gracefully; cancelled")
        logger.info("RAG indexing queue stopped")

    def enqueue(self, job: IndexingJob) -> bool:
        try:
            self._queue.put_nowait(job)
            logger.info(f"Enqueued indexing job: {job.file_path} (workspace={job.workspace_id})")
            return True
        except asyncio.QueueFull:
            logger.warning(f"Indexing queue full, rejecting: {job.file_path}")
            return False

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    async def _worker_loop(self):
        from sage.rag.ingest import IngestionPipeline
        from sage.db.session import AsyncSessionLocal

        while self._running:
            try:
                job = await self._queue.get()
                
                if job is None:
                    break

                logger.info(f"Processing indexing job: {job.file_path}")
                try:
                    pipeline = IngestionPipeline.create_default()
                    async with AsyncSessionLocal() as db:
                        if job.reindex and job.document_id:
                            await pipeline.reindex_file(db, job.document_id)
                        else:
                            await pipeline.ingest_file(db, job.file_path, job.workspace_id, job.document_id)
                    logger.info(f"Indexing complete: {job.file_path}")
                except Exception as e:
                    logger.error(f"Indexing failed for {job.file_path}: {e}", exc_info=True)
                finally:
                    self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in indexing worker: {e}", exc_info=True)
                await asyncio.sleep(1)

indexing_queue: Optional[IndexingQueue] = None
