"""Prepare short user-supplied video samples outside Git; preserve sources/watermarks."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import cv2
import imageio_ffmpeg

SELECTIONS=[
    ('small-boat','16_','海上小船 · 日间',3,8,'船舶目标发现；类别须人工核实'),
    ('distant-boat','21_','远处船舶 · 岸边视角',2,8,'远景目标与背景干扰'),
    ('night-boat','13_','夜间船舶 · 暗光',10,8,'暗光场景测试，不保证检出'),
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'data/demo-videos')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    entries=[]
    with zipfile.ZipFile(args.archive) as archive:
        for ident,prefix,label,start,duration,purpose in SELECTIONS:
            member=next(n for n in archive.namelist() if Path(n).name.startswith(prefix) and n.lower().endswith('.mp4'))
            # Extract a fixed filename only; never trust archive paths for extraction.
            source=output/(ident+'.source.mp4')
            raw=archive.read(member);source.write_bytes(raw)
            target=output/(ident+'.mp4')
            try:
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-ss',str(start),'-i',str(source),'-t',str(duration),'-an','-vf','scale=960:-2','-r','24','-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True,capture_output=True)
            finally:
                source.unlink(missing_ok=True)
            capture=cv2.VideoCapture(str(target))
            fps=capture.get(cv2.CAP_PROP_FPS)
            seconds=capture.get(cv2.CAP_PROP_FRAME_COUNT)/fps
            width=int(capture.get(3));height=int(capture.get(4));capture.release()
            if seconds>30.1 or target.stat().st_size>12*1024*1024:raise ValueError('Sample exceeds upload limits')
            entries.append(dict(id=ident,file=target.name,label=label,purpose=purpose,seconds=round(seconds,2),width=width,height=height,bytes=target.stat().st_size,source=Path(member).name,source_sha256=hashlib.sha256(raw).hexdigest(),clip_start=start,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),provenance='用户提供的搜集素材；保留原有水印；来源授权待确认，不作为训练数据或准确率依据'))
    (output/'manifest.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([dict(id=e['id'],seconds=e['seconds'],bytes=e['bytes']) for e in entries]))

if __name__=='__main__':main()
