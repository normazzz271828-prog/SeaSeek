"""Frozen nine-class ship detector. Original RGB input; no new training."""
import hashlib
import json
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
_lock=threading.Lock()
_model=None
CLASSES=['散装货船','集装箱船','液体运输船','渔船','杂货船','驱逐舰','护卫舰','保障船','航母']
COLORS=['#3DD8C5','#44B5FF','#F3BB50','#FF7880','#A998FF','#86DA7B','#F59ED5','#67D9EE','#E8A26C']

def font(size):
    for path in [str(ROOT/'.tmp/fonts/NotoSansCJKsc-Regular.otf'),'C:/Windows/Fonts/msyh.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
        if Path(path).exists():
            return ImageFont.truetype(path,size)
    return ImageFont.load_default()

def annotate(rgb, predictions):
    image=Image.fromarray(rgb)
    draw=ImageDraw.Draw(image)
    textfont=font(max(14,round(image.width/65)))
    thickness=max(2,round(image.width/500))
    for i,pred in enumerate(predictions):
        points=[tuple(point) for point in pred['points']]
        color=COLORS[pred['class_id']%len(COLORS)]
        draw.line(points+[points[0]],fill=color,width=thickness)
        label=f"{i+1:02d} {pred['category']} {pred['score']:.0%}"
        box=draw.textbbox((0,0),label,font=textfont)
        tw,th=box[2]-box[0]+12,box[3]-box[1]+8
        x=max(0,min(min(p[0] for p in points),image.width-tw))
        y=max(0,min(min(p[1] for p in points)-th,image.height-th))
        draw.rectangle((x,y,x+tw,y+th),fill='#102E40')
        draw.text((x+6,y+4-box[1]),label,font=textfont,fill=color)
    return image

def detect(rgb, confidence=.25):
    global _model
    with _lock:
        if _model is None:
            weights=ROOT/'models/ship_obb.pt'
            expected=json.loads((ROOT/'models/provenance.json').read_text(encoding='utf-8'))['sha256']
            if not weights.is_file():
                raise RuntimeError('船舶模型权重缺失，请按 models/provenance.json 配置。')
            if hashlib.sha256(weights.read_bytes()).hexdigest()!=expected:
                raise RuntimeError('船舶模型权重校验失败。')
            config=ROOT/'.tmp/ultralytics'
            config.mkdir(parents=True,exist_ok=True)
            os.environ.setdefault('YOLO_CONFIG_DIR',str(config))
            import torch
            from ultralytics import YOLO
            torch.set_num_threads(2)
            _model=YOLO(str(weights),task='obb')
        # Ultralytics ndarray inputs use BGR. Keep training-compatible square 1024 geometry.
        result=_model.predict(source=np.ascontiguousarray(rgb[:,:,::-1]),imgsz=1024,
                              conf=confidence,iou=.45,max_det=1000,device='cpu',verbose=False,rect=False)[0]
        predictions=[]
        if result.obb is not None:
            for points,score,cls in zip(result.obb.xyxyxyxy.cpu().numpy(),result.obb.conf.cpu().numpy(),result.obb.cls.cpu().numpy()):
                class_id=int(cls)
                predictions.append(dict(class_id=class_id,category=CLASSES[class_id],score=float(score),points=points.tolist()))
    return annotate(rgb,predictions),predictions
