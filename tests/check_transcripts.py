# -*- coding: utf-8 -*-
"""转写结果质检：列出全部逐字稿、字数，标记空/异常短的。"""
import sys
from pathlib import Path

run = sys.argv[1] if len(sys.argv) > 1 else r"dy_pipeline/data\示例客户\run_20260815_130550"
tdir = Path(run) / "transcripts"
files = sorted(tdir.glob("*.txt"))
print(f"共 {len(files)} 份逐字稿")
total = 0
bad = []
for f in files:
    text = f.read_text(encoding="utf-8").strip()
    n = len(text)
    total += n
    flag = ""
    if n == 0:
        bad.append(f.stem)
        flag = "  <-- 空"
    elif n < 80:
        flag = "  <-- 偏短"
        bad.append(f.stem)
    print(f"{f.stem}: {n} 字{flag}")
print(f"\n总字数 {total}；异常 {len(bad)} 条: {bad}")
