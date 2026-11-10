from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
import json
import logging
from pathlib import Path
import subprocess
from tempfile import TemporaryFile
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from .detection import Detector

Progress = Callable[[str, int, int | None], None]
logger = logging.getLogger(__name__)


class MediaError(Exception):
    pass


def process_image(source: Path, target: Path, detector: 'Detector', report: Progress) -> None:
    with source.open('rb') as file:
        header = file.read(8)
    expected = b'\x89PNG\r\n\x1a\n' if source.suffix.lower() == '.png' else b'\xff\xd8\xff'
    if not header.startswith(expected):
        raise MediaError('图片内容与文件格式不符。')
    # 使用内存编解码，兼容 Windows 下含中文的文件路径。
    frame = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise MediaError('无法读取图片，文件可能已损坏。')
    report('detecting', 0, 1)
    annotated = detector.annotate(frame)
    report('encoding', 1, 1)
    success, encoded = cv2.imencode('.png', annotated)
    if not success:
        raise MediaError('无法生成标注图片。')
    encoded.tofile(target)


@dataclass(frozen=True)
class VideoInfo:
    fps: Fraction
    total: int | None
    has_audio: bool


def inspect_video(source: Path) -> VideoInfo:
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=format_name:format_tags=major_brand:stream=codec_type,codec_name,avg_frame_rate,time_base,nb_frames',
             '-of', 'json', str(source)], capture_output=True, check=True, timeout=30,
        )
        metadata = json.loads(result.stdout)
        format_info = metadata['format']
        if 'mp4' not in format_info['format_name'].split(',') or format_info.get('tags', {}).get('major_brand') == 'qt  ':
            raise MediaError('请使用 MP4 容器的视频。')
        streams = metadata['streams']
        video = next(stream for stream in streams if stream['codec_type'] == 'video')
        audio = next((stream for stream in streams if stream['codec_type'] == 'audio'), None)
        if video['codec_name'] != 'h264' or (audio and audio['codec_name'] != 'aac'):
            raise MediaError('视频需要 H.264 编码，音轨需要 AAC 编码。')
        fps = Fraction(video['avg_frame_rate'])
        ticks_per_frame = 1 / (fps * Fraction(video['time_base']))
        total = video.get('nb_frames', '')
        # 检查包时长，允许时间基舍入产生的一刻度误差，避免变帧率重编码后音画漂移。
        packets = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
             'packet=duration', '-of', 'csv=p=0', str(source)],
            capture_output=True, check=True, timeout=60,
        )
        durations = packets.stdout.splitlines()
        if not durations or any(abs(int(value) - ticks_per_frame) > 1 for value in durations):
            raise MediaError('请使用恒定帧率的视频。')
        return VideoInfo(fps, int(total) if total.isdecimal() and int(total) else None, audio is not None)
    except (subprocess.SubprocessError, OSError, KeyError, ValueError, StopIteration, ZeroDivisionError) as exc:
        raise MediaError('无法读取视频信息，请检查文件是否完整且格式受支持。') from exc


def process_video(source: Path, target: Path, detector: 'Detector', report: Progress) -> None:
    info = inspect_video(source)
    capture = cv2.VideoCapture(str(source), cv2.CAP_FFMPEG)
    try:
        success, frame = capture.read()
        if not success:
            raise MediaError('无法解码视频的第一帧。')
        height, width = frame.shape[:2]
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
                   '-pixel_format', 'bgr24', '-video_size', f'{width}x{height}',
                   '-framerate', str(info.fps), '-i', 'pipe:0']
        if info.has_audio:
            # 补齐短音轨，并以视频结束为准，防止短音轨截掉已检测的视频帧。
            command += ['-i', str(source), '-map', '0:v:0', '-map', '1:a:0',
                        '-c:a', 'aac', '-af', 'apad', '-shortest']
        command += ['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264',
                    '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)]

        with TemporaryFile() as errors:
            encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
            assert encoder.stdin is not None
            frames = 0
            report('detecting', frames, info.total)
            try:
                while success:
                    if frame.shape[:2] != (height, width):
                        raise MediaError('视频帧的分辨率发生变化。')
                    annotated = detector.annotate(frame)
                    encoder.stdin.write(annotated.tobytes())
                    frames += 1
                    report('detecting', frames, info.total)
                    success, frame = capture.read()
                if info.total and frames != info.total:
                    raise MediaError('视频实际解码帧数与文件信息不符，文件可能已损坏。')
                report('encoding', frames, info.total)
                encoder.stdin.close()
                if encoder.wait(timeout=60) != 0:
                    raise MediaError('FFmpeg 视频编码失败，请查看后端日志。')
            except (BrokenPipeError, subprocess.TimeoutExpired) as exc:
                raise MediaError('FFmpeg 视频编码失败，请查看后端日志。') from exc
            finally:
                if encoder.poll() is None:
                    encoder.kill()
                    encoder.wait()
                try:
                    encoder.stdin.close()
                except BrokenPipeError:
                    pass
                # 管道关闭后再读取日志，避免 FFmpeg 因写满标准错误管道而阻塞。
                if encoder.returncode:
                    errors.seek(0)
                    logger.error('FFmpeg exit %s: %s', encoder.returncode,
                                 errors.read(8192).decode(errors='replace'))
    finally:
        capture.release()
