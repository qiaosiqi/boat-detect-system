# 基于 YOLO26s 的船只对象识别系统

单机实训项目。网页支持本地上传和 8 个内置样例，可预览原件、提交检测、查看进度以及预览或下载标注结果。船只（`boat`）使用绿色边界框，模型检出的其他 COCO 类别使用红色边界框。

## Windows 安装

准备 Python 3.12、Node.js 22.12+（可用 Node.js 24）以及含 `libx264`、AAC 编码器的 FFmpeg。将 `ffmpeg` 和 `ffprobe` 添加到 `PATH`。以下命令从项目根目录在 PowerShell 中执行。

```powershell
python -m venv .venv
ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -encoders | Select-String 'libx264| aac '
```

选择一组 PyTorch 安装命令。有兼容 CUDA 12.8 的 NVIDIA 驱动时使用 GPU 版，否则使用 CPU 版。所有 Python 命令都使用项目虚拟环境，无需手动激活。

```powershell
# NVIDIA GPU 版
.\.venv\Scripts\python.exe -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128

# 或使用 Windows x64 CPU 版
.\.venv\Scripts\python.exe -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://pypi.org/simple
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pip check
New-Item -ItemType Directory -Force models | Out-Null
curl.exe --fail --location https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt --output models/yolo26s.pt
npm.cmd --prefix frontend ci
```

权重 SHA-256 为 `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b`。也可从 [Ultralytics 发布的 YOLO26 权重仓库](https://huggingface.co/Ultralytics/YOLO26/resolve/070ac3c51435984d992ba92eb3f234daf4e4500d/yolo26s.pt) 下载同一文件。

## 启动与演示

在两个 PowerShell 窗口中分别从项目根目录运行：

```powershell
# 窗口一。后端日志会显示实际推理设备。
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

```powershell
# 窗口二
npm.cmd --prefix frontend run dev
```

打开 [本地演示页面](http://127.0.0.1:5173)，选择图片或视频模式，再选一个内置样例或本地文件。确认原件后点击 **开始检测**，完成后在右侧预览或点击 **下载结果**。API 可在 [接口文档](http://127.0.0.1:8000/docs) 查看。前端构建检查使用 `npm.cmd --prefix frontend run build`。

可用 `pic04.jpg` 演示同一画面中的红绿框，用 `vid02.mp4` 演示带声音的视频。CPU 模式处理视频的时间取决于帧数和本机性能。

| 输入 | 格式 | 上传上限 | 输出 |
| --- | --- | --- | --- |
| 图片 | JPEG、PNG | 20 MiB | PNG |
| 视频 | 恒定帧率的 H.264 MP4，可带 AAC 音轨 | 500 MiB | H.264 MP4，保留首条音轨 |

系统同一时间处理一个任务。上传原件与标注结果保存在 `runs/<任务 ID>/`，内置样例从 `data/` 读取。重启后可直接打开磁盘中的已生成文件，网页任务地址随进程重启失效。
