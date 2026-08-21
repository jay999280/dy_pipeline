# -*- coding: utf-8 -*-
"""最小复现：加载本地 faster-whisper 模型，定位报错点。"""
import sys
import traceback
from pathlib import Path

local = Path(r"dy_pipeline/data\models\faster-whisper-small")
print("model dir files:")
for f in sorted(local.iterdir()):
    print("  ", f.name, f.stat().st_size)

try:
    import ctranslate2
    print("ctranslate2 version:", ctranslate2.__version__)
    from faster_whisper import WhisperModel
    print("loading model ...")
    m = WhisperModel(str(local), device="cpu", compute_type="int8")
    print("model loaded ok")
    # 生成 1 秒静音 wav 测试
    import subprocess
    wav = local / "test_silence.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", "1", "-ar", "16000", str(wav)], check=True, capture_output=True)
    segs, info = m.transcribe(str(wav), language="zh", vad_filter=True)
    text = "".join(s.text for s in segs)
    print("transcribe ok, text =", repr(text))
except Exception:
    traceback.print_exc()
