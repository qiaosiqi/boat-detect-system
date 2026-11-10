from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from .detection import Detector
from .media import MediaError, process_image, process_video

MediaKind = Literal['image', 'video']
logger = logging.getLogger(__name__)


@dataclass
class Task:
    id: str
    kind: MediaKind
    status: str = 'queued'
    stage: str = 'queued'
    progress: int | None = 0
    frames_processed: int = 0
    total_frames: int | None = None
    error: str | None = None
    result: Path | None = None

    def snapshot(self) -> dict:
        return {
            'id': self.id, 'kind': self.kind, 'status': self.status,
            'stage': self.stage, 'progress': self.progress,
            'frames_processed': self.frames_processed, 'total_frames': self.total_frames,
            'error': self.error,
            'result_url': f'/api/tasks/{self.id}/result' if self.result else None,
        }


class TaskManager:
    def __init__(self, detector: Detector):
        self.detector = detector
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='detection')
        self.lock = Lock()
        self.active_id: str | None = None
        self.tasks: dict[str, Task] = {}

    def reserve(self) -> str | None:
        # 在读取上传表单前占用槽位，两个请求不能同时进入准备或检测阶段。
        with self.lock:
            if self.active_id is not None:
                return None
            self.active_id = uuid4().hex
            return self.active_id

    def abandon(self, task_id: str) -> None:
        with self.lock:
            if self.active_id == task_id:
                self.active_id = None

    def submit(self, task_id: str, kind: MediaKind, source: Path, directory: Path) -> None:
        with self.lock:
            task = Task(task_id, kind)
            self.tasks[task_id] = task
            try:
                self.executor.submit(self._run, task, source, directory)
            except RuntimeError:
                del self.tasks[task_id]
                raise

    def status(self, task_id: str) -> dict | None:
        with self.lock:
            task = self.tasks.get(task_id)
            return task.snapshot() if task else None

    def result(self, task_id: str) -> Path | None:
        with self.lock:
            task = self.tasks.get(task_id)
            return task.result if task and task.status == 'succeeded' else None

    def _run(self, task: Task, source: Path, directory: Path) -> None:
        suffix = '.png' if task.kind == 'image' else '.mp4'
        temporary = directory / f'result.part{suffix}'
        final = directory / f'result{suffix}'
        error = None

        def report(stage: str, frames: int, total: int | None) -> None:
            with self.lock:
                task.stage = stage
                task.frames_processed = frames
                task.total_frames = total
                # 100% 仅在编码结束、文件正式可访问后显示。
                task.progress = min(99, frames * 100 // total) if total else None

        try:
            with self.lock:
                task.status = 'running'
                task.stage = 'reading'
            if task.kind == 'image':
                process_image(source, temporary, self.detector, report)
            else:
                process_video(source, temporary, self.detector, report)
            temporary.replace(final)
        except MediaError as exc:
            error = str(exc)
            logger.warning('Task %s: %s', task.id, error)
        except Exception:
            error = '检测失败，请查看后端日志。'
            logger.exception('Task %s failed', task.id)
        finally:
            # 编码或推理失败时删除半成品，释放槽位与更新终态放在同一把锁内。
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.exception('Could not remove temporary file for task %s', task.id)
            with self.lock:
                task.error = error
                task.status = 'failed' if error else 'succeeded'
                task.stage = task.status
                if not error:
                    task.result = final
                    task.progress = 100
                self.active_id = None
