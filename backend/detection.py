import logging
import os
from pathlib import Path

import cv2
import numpy as np
import torch


class Detector:
    def __init__(self, weights: Path):
        # 演示仅使用本地权重，Ultralytics 的运行配置也保存在项目目录中。
        os.environ.setdefault('YOLO_CONFIG_DIR', str(weights.parent.parent / 'runs' / '.ultralytics'))
        os.environ.setdefault('YOLO_OFFLINE', 'true')
        from ultralytics import YOLO

        self.device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        self.model = YOLO(str(weights), task='detect')
        if 'boat' not in self.model.names.values():
            raise RuntimeError('当前检测权重缺少 boat 类别，请使用官方 yolo26s.pt。')
        logging.getLogger('uvicorn.error').info('YOLO26s inference device: %s', self.device)

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        prediction = self.model.predict(frame, imgsz=640, conf=0.25, device=self.device, verbose=False)[0]
        height, width = frame.shape[:2]
        thickness = max(2, round(min(height, width) / 400))
        font_scale = max(0.5, thickness / 3)
        for x1, y1, x2, y2, confidence, category in prediction.boxes.data.cpu().tolist():
            name = prediction.names[int(category)]
            # OpenCV 使用 BGR 通道顺序。按类别名判断，避免依赖固定类别编号。
            color = (0, 255, 0) if name == 'boat' else (0, 0, 255)
            left, right = [max(0, min(width - 1, round(x))) for x in (x1, x2)]
            top, bottom = [max(0, min(height - 1, round(y))) for y in (y1, y2)]
            cv2.rectangle(frame, (left, top), (right, bottom), color, thickness)
            label = f'{name} {confidence:.0%}'
            (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            text_x = max(0, min(left, width - text_width - 4))
            text_y = min(height - 1, max(text_height + 3, top - baseline - 3))
            cv2.rectangle(frame, (text_x, text_y - text_height - 3),
                          (text_x + text_width + 4, text_y + baseline + 2), color, cv2.FILLED)
            cv2.putText(frame, label, (text_x + 2, text_y), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, (0, 0, 0), 1, cv2.LINE_AA)
        return frame
