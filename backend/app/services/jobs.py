from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.services.folder_scan import ScanResult
from backend.app.services.mosaic import MosaicClient, execute_mosaic
from backend.app.services.rename import execute_rename
from backend.app.services.upscale import ComfyUIClient, execute_upscale
from backend.app.services.pipeline import execute_pipeline


TERMINAL_STATES = {"completed", "failed", "cancelled"}
ACTIVE_STATES = {"queued", "running", "cancel_requested"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, input_folder TEXT NOT NULL,
                    output_folder TEXT NOT NULL, enabled_steps TEXT NOT NULL,
                    settings TEXT NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, source_name TEXT NOT NULL, source_path TEXT NOT NULL,
                    group_name TEXT NOT NULL, output_name TEXT NOT NULL, output_path TEXT NOT NULL,
                    status TEXT NOT NULL, error TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
                    validation_result TEXT, UNIQUE(job_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS image_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    error TEXT, input_path TEXT, output_path TEXT, UNIQUE(image_id, name)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_images_job ON images(job_id, ordinal);
                """
            )

    def recover_interrupted(self) -> int:
        timestamp = _now()
        message = "アプリの異常終了により処理を中断しました。"
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT id FROM jobs WHERE status IN ('running', 'cancel_requested')").fetchall()
            ids = [row["id"] for row in rows]
            for job_id in ids:
                db.execute("UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?", (timestamp, message, job_id))
                db.execute("UPDATE images SET status='failed', error=? WHERE job_id=? AND status='running'", (message, job_id))
                db.execute(
                    "UPDATE image_steps SET status='failed', finished_at=?, error=? "
                    "WHERE image_id IN (SELECT id FROM images WHERE job_id=?) AND status='running'",
                    (timestamp, message, job_id),
                )
            return len(ids)

    def create(self, scan: ScanResult, enabled_steps: list[str], settings: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?, 'queued', ?, NULL, NULL, ?, ?, ?, ?, NULL)",
                (job_id, _now(), scan.input_folder, scan.output_folder, json.dumps(enabled_steps), json.dumps(settings)),
            )
            for ordinal, image in enumerate(scan.images, 1):
                cursor = db.execute(
                    "INSERT INTO images (job_id, ordinal, source_name, source_path, group_name, output_name, output_path, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')",
                    (job_id, ordinal, image.source_name, image.source_path, image.group, image.output_name, image.output_path),
                )
                for step in enabled_steps:
                    db.execute("INSERT INTO image_steps (image_id, name, status) VALUES (?, ?, 'queued')", (cursor.lastrowid, step))
        return job_id

    def queued_ids(self) -> list[str]:
        with self._connect() as db:
            return [row["id"] for row in db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at")]

    def set_job_status(self, job_id: str, status: str, *, error: str | None = None) -> None:
        with self._lock, self._connect() as db:
            if status == "running":
                db.execute("UPDATE jobs SET status=?, started_at=COALESCE(started_at, ?) WHERE id=?", (status, _now(), job_id))
            elif status in TERMINAL_STATES:
                db.execute("UPDATE jobs SET status=?, finished_at=?, error=? WHERE id=?", (status, _now(), error, job_id))
                if status == "cancelled":
                    db.execute("UPDATE images SET status='cancelled' WHERE job_id=? AND status='queued'", (job_id,))
                    db.execute(
                        "UPDATE image_steps SET status='cancelled' WHERE image_id IN "
                        "(SELECT id FROM images WHERE job_id=?) AND status='queued'",
                        (job_id,),
                    )
            else:
                db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))

    def status(self, job_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            return row["status"] if row else None

    def has_active_jobs(self) -> bool:
        with self._connect() as db:
            placeholders = ",".join("?" for _ in ACTIVE_STATES)
            row = db.execute(
                f"SELECT 1 FROM jobs WHERE status IN ({placeholders}) LIMIT 1",
                tuple(ACTIVE_STATES),
            ).fetchone()
            return row is not None

    def run_test_image(self, job_id: str, image_id: int) -> None:
        started = _now()
        with self._lock, self._connect() as db:
            db.execute("UPDATE images SET status='running' WHERE id=? AND job_id=?", (image_id, job_id))
            db.execute("UPDATE image_steps SET status='running', started_at=? WHERE image_id=?", (started, image_id))
        finished = _now()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE image_steps SET status='completed', finished_at=?, input_path=(SELECT source_path FROM images WHERE id=?), "
                "output_path=(SELECT output_path FROM images WHERE id=?) WHERE image_id=?",
                (finished, image_id, image_id, image_id),
            )
            db.execute("UPDATE images SET status='completed', validation_result='test_job' WHERE id=?", (image_id,))

    def run_rename_image(self, job_id: str, image_id: int) -> None:
        started = _now()
        with self._lock, self._connect() as db:
            image = db.execute("SELECT * FROM images WHERE id=? AND job_id=?", (image_id, job_id)).fetchone()
            if image is None:
                raise RuntimeError("処理対象の画像が見つかりません。")
            db.execute("UPDATE images SET status='running', error=NULL WHERE id=?", (image_id,))
            db.execute(
                "UPDATE image_steps SET status='running', started_at=?, finished_at=NULL, error=NULL, "
                "input_path=?, output_path=NULL WHERE image_id=? AND name='rename'",
                (started, image["source_path"], image_id),
            )
        try:
            source = Path(image["source_path"])
            with Image.open(source) as opened:
                expected_size = opened.size
                opened.verify()
            output_path = execute_rename(
                source_path=image["source_path"], output_path=image["output_path"],
                expected_size=expected_size, job_id=job_id, image_id=image_id,
            )
        except Exception as exc:
            finished = _now()
            with self._lock, self._connect() as db:
                db.execute("UPDATE images SET status='failed', error=? WHERE id=?", (str(exc), image_id))
                db.execute(
                    "UPDATE image_steps SET status='failed', finished_at=?, error=? "
                    "WHERE image_id=? AND name='rename'",
                    (finished, str(exc), image_id),
                )
            return
        finished = _now()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE image_steps SET status='completed', finished_at=?, output_path=? "
                "WHERE image_id=? AND name='rename'", (finished, output_path, image_id),
            )
            db.execute(
                "UPDATE images SET status='completed', error=NULL, validation_result=? WHERE id=?",
                (json.dumps({"format": "PNG", "size": list(expected_size)}, ensure_ascii=False), image_id),
            )

    def run_upscale_image(self, job_id: str, image_id: int, client: ComfyUIClient) -> None:
        started = _now()
        with self._lock, self._connect() as db:
            image = db.execute("SELECT * FROM images WHERE id=? AND job_id=?", (image_id, job_id)).fetchone()
            if image is None:
                raise RuntimeError("処理対象の画像が見つかりません。")
            db.execute("UPDATE images SET status='running', error=NULL WHERE id=?", (image_id,))
            db.execute(
                "UPDATE image_steps SET status='completed', started_at=?, finished_at=?, input_path=?, output_path=? "
                "WHERE image_id=? AND name='rename'",
                (started, started, image["source_path"], image["source_path"], image_id),
            )
            db.execute(
                "UPDATE image_steps SET status='running', started_at=?, finished_at=NULL, error=NULL, "
                "input_path=?, output_path=NULL WHERE image_id=? AND name='upscale'",
                (started, image["source_path"], image_id),
            )
        try:
            source = Path(image["source_path"])
            with Image.open(source) as opened:
                source_size = opened.size
                opened.verify()
            expected_size = (source_size[0] * 2, source_size[1] * 2)
            output_path = execute_upscale(
                client=client, source_path=image["source_path"], output_path=image["output_path"],
                expected_size=expected_size, job_id=job_id, image_id=image_id,
                output_subfolder=client.config.output_subfolder,
            )
        except Exception as exc:
            finished = _now()
            with self._lock, self._connect() as db:
                db.execute("UPDATE images SET status='failed', error=? WHERE id=?", (str(exc), image_id))
                db.execute(
                    "UPDATE image_steps SET status='failed', finished_at=?, error=? "
                    "WHERE image_id=? AND name='upscale'", (finished, str(exc), image_id),
                )
            return
        finished = _now()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE image_steps SET status='completed', finished_at=?, output_path=? "
                "WHERE image_id=? AND name='upscale'", (finished, output_path, image_id),
            )
            db.execute(
                "UPDATE images SET status='completed', error=NULL, validation_result=? WHERE id=?",
                (json.dumps({"format": "PNG", "source_size": list(source_size),
                             "size": list(expected_size)}, ensure_ascii=False), image_id),
            )

    def run_mosaic_image(self, job_id: str, image_id: int, client: MosaicClient, strength: int) -> None:
        started = _now()
        with self._lock, self._connect() as db:
            image = db.execute("SELECT * FROM images WHERE id=? AND job_id=?", (image_id, job_id)).fetchone()
            if image is None:
                raise RuntimeError("処理対象の画像が見つかりません。")
            db.execute("UPDATE images SET status='running', error=NULL WHERE id=?", (image_id,))
            db.execute(
                "UPDATE image_steps SET status='completed', started_at=?, finished_at=?, input_path=?, output_path=? "
                "WHERE image_id=? AND name='rename'",
                (started, started, image["source_path"], image["source_path"], image_id),
            )
            db.execute(
                "UPDATE image_steps SET status='running', started_at=?, finished_at=NULL, error=NULL, "
                "input_path=?, output_path=NULL WHERE image_id=? AND name='mosaic'",
                (started, image["source_path"], image_id),
            )
        try:
            source = Path(image["source_path"])
            with Image.open(source) as opened:
                expected_size = opened.size
                opened.verify()
            output_path = execute_mosaic(
                client=client, source_path=image["source_path"], output_path=image["output_path"],
                expected_size=expected_size, strength=strength, job_id=job_id, image_id=image_id,
            )
        except Exception as exc:
            finished = _now()
            with self._lock, self._connect() as db:
                db.execute("UPDATE images SET status='failed', error=? WHERE id=?", (str(exc), image_id))
                db.execute("UPDATE image_steps SET status='failed', finished_at=?, error=? WHERE image_id=? AND name='mosaic'",
                           (finished, str(exc), image_id))
            return
        finished = _now()
        with self._lock, self._connect() as db:
            db.execute("UPDATE image_steps SET status='completed', finished_at=?, output_path=? WHERE image_id=? AND name='mosaic'",
                       (finished, output_path, image_id))
            db.execute("UPDATE images SET status='completed', error=NULL, validation_result=? WHERE id=?",
                       (json.dumps({"format": "PNG", "size": list(expected_size), "mosaic_strength": strength}, ensure_ascii=False), image_id))

    def run_pipeline_image(self, job_id: str, image_id: int, upscale_client: ComfyUIClient | None,
                           mosaic_client: MosaicClient | None) -> None:
        with self._lock, self._connect() as db:
            image = db.execute("SELECT * FROM images WHERE id=? AND job_id=?", (image_id, job_id)).fetchone()
            job = db.execute("SELECT enabled_steps, settings FROM jobs WHERE id=?", (job_id,)).fetchone()
            if image is None or job is None:
                raise RuntimeError("処理対象の画像が見つかりません。")
            enabled_steps = json.loads(job["enabled_steps"])
            settings = json.loads(job["settings"])
            db.execute("UPDATE images SET status='running', error=NULL WHERE id=?", (image_id,))

        def update_step(name: str, status: str, input_path: str | None, detail: str | None) -> None:
            timestamp = _now()
            with self._lock, self._connect() as db:
                if status == "running":
                    db.execute(
                        "UPDATE image_steps SET status='running', started_at=?, finished_at=NULL, error=NULL, input_path=?, output_path=NULL "
                        "WHERE image_id=? AND name=?", (timestamp, input_path, image_id, name),
                    )
                elif status == "completed":
                    db.execute(
                        "UPDATE image_steps SET status='completed', finished_at=?, output_path=? WHERE image_id=? AND name=?",
                        (timestamp, detail, image_id, name),
                    )
                else:
                    db.execute(
                        "UPDATE image_steps SET status='failed', finished_at=?, error=? WHERE image_id=? AND name=?",
                        (timestamp, detail, image_id, name),
                    )

        try:
            validation = execute_pipeline(
                source_path=image["source_path"], output_path=image["output_path"], enabled_steps=enabled_steps,
                settings=settings, job_id=job_id, image_id=image_id, upscale_client=upscale_client,
                mosaic_client=mosaic_client, on_step=update_step,
            )
        except Exception as exc:
            with self._lock, self._connect() as db:
                db.execute("UPDATE images SET status='failed', error=? WHERE id=?", (str(exc), image_id))
            return
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE images SET status='completed', error=NULL, validation_result=? WHERE id=?",
                (json.dumps(validation, ensure_ascii=False), image_id),
            )

    def image_ids(self, job_id: str) -> list[int]:
        with self._connect() as db:
            return [row["id"] for row in db.execute("SELECT id FROM images WHERE job_id=? AND status='queued' ORDER BY ordinal", (job_id,))]

    def is_test_job(self, job_id: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT settings FROM jobs WHERE id=?", (job_id,)).fetchone()
            return bool(row and json.loads(row["settings"]).get("_test_job"))

    def prepare_failed_retry(self, job_id: str) -> bool:
        with self._lock, self._connect() as db:
            job = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None or job["status"] != "failed":
                return False
            failed = db.execute("SELECT id FROM images WHERE job_id=? AND status='failed'", (job_id,)).fetchall()
            if not failed:
                return False
            ids = [row["id"] for row in failed]
            placeholders = ",".join("?" for _ in ids)
            db.execute(
                "UPDATE jobs SET status='queued', started_at=NULL, finished_at=NULL, error=NULL WHERE id=?", (job_id,)
            )
            db.execute(
                f"UPDATE images SET status='queued', error=NULL, retry_count=retry_count+1 WHERE id IN ({placeholders})", ids
            )
            db.execute(
                f"UPDATE image_steps SET status='queued', started_at=NULL, finished_at=NULL, error=NULL, "
                f"input_path=NULL, output_path=NULL WHERE image_id IN ({placeholders})", ids
            )
            return True

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return None
            images = db.execute("SELECT * FROM images WHERE job_id=? ORDER BY ordinal", (job_id,)).fetchall()
            result = dict(job)
            result["enabled_steps"] = json.loads(result["enabled_steps"])
            result["settings"] = json.loads(result["settings"])
            result["images"] = []
            for image in images:
                item = dict(image)
                item["steps"] = [dict(row) for row in db.execute("SELECT * FROM image_steps WHERE image_id=? ORDER BY id", (image["id"],))]
                result["images"].append(item)
            counts = {state: 0 for state in ("queued", "running", "completed", "failed", "cancelled")}
            for item in result["images"]:
                counts[item["status"]] = counts.get(item["status"], 0) + 1
            result["counts"] = counts
            result["total_count"] = len(images)
            result["processed_count"] = sum(counts.get(state, 0) for state in TERMINAL_STATES)
            return result

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM jobs ORDER BY created_at DESC")]
        return [item for job_id in ids if (item := self.snapshot(job_id)) is not None]

    def clear_terminal(self) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM jobs WHERE status IN ('completed', 'failed', 'cancelled')")
            return cursor.rowcount


class JobManager:
    def __init__(self, store: JobStore, upscale_client: ComfyUIClient | None = None,
                 mosaic_client: MosaicClient | None = None) -> None:
        self.store = store
        self.upscale_client = upscale_client
        self.mosaic_client = mosaic_client
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.store._initialize()
        self.store.recover_interrupted()
        for job_id in self.store.queued_ids():
            self.queue.put_nowait(job_id)
        self.worker = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    async def enqueue(self, scan: ScanResult, enabled_steps: list[str], settings: dict[str, Any]) -> dict[str, Any]:
        job_id = self.store.create(scan, enabled_steps, settings)
        await self.queue.put(job_id)
        return self.store.snapshot(job_id) or {}

    async def retry_failed(self, job_id: str) -> dict[str, Any] | None:
        if not self.store.prepare_failed_retry(job_id):
            return None
        await self.queue.put(job_id)
        return self.store.snapshot(job_id)

    async def cancel(self, job_id: str) -> bool:
        status = self.store.status(job_id)
        if status not in {"queued", "running"}:
            return False
        self.store.set_job_status(job_id, "cancel_requested")
        await self._publish(job_id)
        return True

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                if self.store.status(job_id) == "cancel_requested":
                    self.store.set_job_status(job_id, "cancelled")
                    await self._publish(job_id)
                    continue
                self.store.set_job_status(job_id, "running")
                await self._publish(job_id)
                for image_id in self.store.image_ids(job_id):
                    if self.store.status(job_id) == "cancel_requested":
                        self.store.set_job_status(job_id, "cancelled")
                        break
                    if self.store.is_test_job(job_id):
                        self.store.run_test_image(job_id, image_id)
                    else:
                        await asyncio.to_thread(
                            self.store.run_pipeline_image, job_id, image_id, self.upscale_client, self.mosaic_client
                        )
                    await self._publish(job_id)
                    await asyncio.sleep(0)
                else:
                    snapshot = self.store.snapshot(job_id)
                    if snapshot and snapshot["counts"].get("failed", 0):
                        self.store.set_job_status(job_id, "failed", error="一部の画像を処理できませんでした。")
                    else:
                        self.store.set_job_status(job_id, "completed")
                await self._publish(job_id)
            except Exception as exc:
                self.store.set_job_status(job_id, "failed", error=str(exc))
                await self._publish(job_id)
            finally:
                self.queue.task_done()

    async def _publish(self, job_id: str) -> None:
        snapshot = self.store.snapshot(job_id)
        if snapshot is None:
            return
        for queue in list(self.subscribers.get(job_id, set())):
            queue.put_nowait(snapshot)

    async def events(self, job_id: str) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.setdefault(job_id, set()).add(queue)
        initial = self.store.snapshot(job_id)
        if initial:
            queue.put_nowait(initial)
        try:
            while True:
                try:
                    snapshot = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: job\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                    if snapshot["status"] in TERMINAL_STATES:
                        return
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.subscribers.get(job_id, set()).discard(queue)
