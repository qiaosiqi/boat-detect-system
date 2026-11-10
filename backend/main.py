from contextlib import asynccontextmanager
from pathlib import Path
import shutil

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .detection import Detector
from .tasks import MediaKind, TaskManager

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {
    **{f'pic{i:02}': ('image', ROOT / 'data' / 'picture' / f'pic{i:02}.jpg') for i in range(1, 7)},
    **{f'vid{i:02}': ('video', ROOT / 'data' / 'video' / f'vid{i:02}.mp4') for i in range(1, 3)},
}
MEBIBYTE = 1024 * 1024
LIMITS = {'image': 20 * MEBIBYTE, 'video': 500 * MEBIBYTE}
MEDIA_TYPES: dict[str, MediaKind] = {'.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.mp4': 'video'}


@asynccontextmanager
async def lifespan(app: FastAPI):
    weights = ROOT / 'models' / 'yolo26s.pt'
    if not weights.is_file():
        raise RuntimeError('缺少 models/yolo26s.pt，请按 README 下载官方权重。')
    if not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')):
        raise RuntimeError('请安装 FFmpeg，并将 ffmpeg 和 ffprobe 加入 PATH。')
    app.state.tasks = TaskManager(Detector(weights))
    try:
        yield
    finally:
        await run_in_threadpool(app.state.tasks.executor.shutdown)


app = FastAPI(title='船只对象识别系统', lifespan=lifespan)


@app.get('/api/samples')
def list_samples():
    return [{'id': sample_id, 'kind': kind, 'name': path.name, 'url': f'/api/samples/{sample_id}'}
            for sample_id, (kind, path) in SAMPLES.items() if path.is_file()]


@app.get('/api/samples/{sample_id}')
def get_sample(sample_id: str):
    _, path = find_sample(sample_id)
    return FileResponse(path)


def find_sample(sample_id: str):
    sample = SAMPLES.get(sample_id)
    if sample is None or not sample[1].is_file():
        raise HTTPException(404, '未找到该演示素材。')
    return sample


@app.post('/api/tasks', status_code=202)
async def create_task(request: Request):
    manager: TaskManager = request.app.state.tasks
    task_id = manager.reserve()
    if task_id is None:
        raise HTTPException(409, '已有检测任务正在处理，请稍后重试。')

    directory = ROOT / 'runs' / task_id
    submitted = False
    try:
        content_length = request.headers.get('content-length')
        if content_length and content_length.isdecimal() and int(content_length) > LIMITS['video'] + MEBIBYTE:
            raise HTTPException(413, '上传文件超过 500 MiB。')
        async with request.form(max_files=1, max_fields=1) as form:
            file, sample_id = form.get('file'), form.get('sample_id')
            if isinstance(sample_id, str) and sample_id and file is None:
                kind, source = find_sample(sample_id)
                directory.mkdir(parents=True)
            elif isinstance(file, UploadFile) and sample_id is None:
                suffix = Path(file.filename or '').suffix.lower()
                kind = MEDIA_TYPES.get(suffix)
                if kind is None:
                    raise HTTPException(415, '请选择 JPEG、PNG 图片或 MP4 视频。')
                size = file.size or 0
                if size > LIMITS[kind]:
                    raise HTTPException(413, f'文件超过 {LIMITS[kind] // MEBIBYTE} MiB。')
                if not size:
                    raise HTTPException(400, '上传文件为空。')
                directory.mkdir(parents=True)
                source = directory / f'input{suffix}'
                await run_in_threadpool(save_upload, file, source)
            else:
                raise HTTPException(400, '请上传一个文件或选择一个样例。')
        manager.submit(task_id, kind, source, directory)
        submitted = True
        return {'id': task_id}
    finally:
        if not submitted:
            # 文件准备失败时同样释放工作槽位，下一次提交可以继续。
            try:
                if directory.exists():
                    shutil.rmtree(directory)
            finally:
                manager.abandon(task_id)


def save_upload(file: UploadFile, destination: Path) -> None:
    with destination.open('wb') as output:
        shutil.copyfileobj(file.file, output, length=MEBIBYTE)


@app.get('/api/tasks/{task_id}')
def get_task(task_id: str, request: Request):
    status = request.app.state.tasks.status(task_id)
    if status is None:
        raise HTTPException(404, '未找到该检测任务。')
    return status


@app.get('/api/tasks/{task_id}/result')
def get_result(task_id: str, request: Request, download: bool = False):
    path = request.app.state.tasks.result(task_id)
    if path is None or not path.is_file():
        raise HTTPException(404, '标注结果尚不可用。')
    return FileResponse(path, filename=f'annotated-{task_id[:8]}{path.suffix}',
                        content_disposition_type='attachment' if download else 'inline')
