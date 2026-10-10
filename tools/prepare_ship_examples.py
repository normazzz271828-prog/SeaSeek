"""Read-only reuse of source train split. Never selects val/confirm/test."""
import json
import subprocess
from pathlib import Path
from collections import Counter

import cv2
import imageio_ffmpeg
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('D:/Projects/海面目标检测与识别/accuracy_lab/prepared_v2')
manifest=json.loads((SOURCE/'manifest.json').read_text(encoding='utf-8'))
records=json.loads((SOURCE/manifest['records_file']).read_text(encoding='utf-8'))
train=[r for r in records if r['split']=='train']
out=ROOT/'assets/examples';out.mkdir(parents=True,exist_ok=True)
mapping=json.loads((out/'sources.json').read_text(encoding='utf-8'))
used={m['source'] for m in mapping}
chosen=[]
for category in range(9):
    candidates=[r for r in train if r['image'] not in used and any(l['class_id']==category for l in r['labels'])]
    # Select two examples per class from the source train records; retain actual class labels in manifest.
    candidates.sort(key=lambda r:max((abs(l['points'][1][0]-l['points'][0][0])+abs(l['points'][1][1]-l['points'][0][1]) for l in r['labels'] if l['class_id']==category),default=0),reverse=True)
    for j,r in enumerate(candidates[:2]):
        target=f"{manifest['class_names'][category]}_{j+1:02d}_{Path(r['image']).stem}.jpg"
        with Image.open(Path(manifest['raw_root'])/r['image']) as source:
            image=ImageOps.exif_transpose(source).convert('RGB');image.thumbnail((1600,1600));image.save(out/target,quality=91)
        mapping.append(dict(file=target,source=r['image'],split='train',class_ids=sorted({l['class_id'] for l in r['labels']})))
        used.add(r['image']);chosen.append(out/target)
(out/'sources.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
counts=Counter(l['class_id'] for r in train for l in r['labels'])
(ROOT/'assets/dataset_summary.json').write_text(json.dumps(dict(source=str(SOURCE),training_images=len(train),training_objects=sum(counts.values()),class_names=manifest['class_names'],class_counts=dict(counts),example_images=len(mapping),policy='train only; no new training or accuracy claim'),ensure_ascii=False,indent=2),encoding='utf-8')
# Four stills, each two seconds: explicitly a synthetic video for exercising the pipeline.
temp=ROOT/'.tmp/slideshow.mp4';temp.parent.mkdir(exist_ok=True)
writer=cv2.VideoWriter(str(temp),cv2.VideoWriter_fourcc(*'mp4v'),10,(960,540))
if not writer.isOpened():raise RuntimeError('video writer unavailable')
for path in chosen[::4][:4]:
    image=Image.open(path);image.thumbnail((960,540));canvas=Image.new('RGB',(960,540),(12,37,55));canvas.paste(image,((960-image.width)//2,(540-image.height)//2))
    import numpy as np
    frame=cv2.cvtColor(np.asarray(canvas),cv2.COLOR_RGB2BGR)
    for _ in range(20):writer.write(frame)
writer.release()
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-i',str(temp),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(ROOT/'assets/demo_ships.mp4')],check=True,capture_output=True)
print('Prepared',len(mapping),'train examples;',len(train),'source train images; synthetic demo video ready.')
