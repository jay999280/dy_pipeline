# -*- coding: utf-8 -*-
"""诊断：赛道倾向分布 vs 代表视频分配。"""
import json
from pathlib import Path

d = Path(r"dy_pipeline/data\示例客户\run_20260815_130550")
an = json.load(open(d / "analysis.json", encoding="utf-8"))["视频分析"]
cand = {v["aweme_id"]: v for v in json.load(open(d / "candidates.json", encoding="utf-8"))["视频"]}
tracks = json.load(open(d / "tracks.json", encoding="utf-8"))["赛道"]

print("=== tracks.json 当前代表视频 ===")
for t in tracks:
    print(f"  {t['名称']}: {t.get('代表视频')}")

print("\n=== 每条视频的赛道倾向 ===")
from collections import Counter
倾向 = Counter(a.get("赛道倾向", "无") for a in an)
for k, v in 倾向.most_common():
    print(f"  [{k}] × {v}")

print("\n=== 倾向-点赞明细 ===")
for a in sorted(an, key=lambda x: -(cand.get(x['video_id'], {}).get('digg_count', 0))):
    vid = a.get("video_id")
    print(f"  {vid} | {cand.get(vid,{}).get('digg_count',0):>7} 赞 | 倾向: {a.get('赛道倾向')} | {cand.get(vid,{}).get('desc','')[:24]}")
