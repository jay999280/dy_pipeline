# -*- coding: utf-8 -*-
"""一次性修复：用确定性算法重算当前 tracks.json 的代表视频（不重跑聚类 LLM）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cluster import assign_reps

d = Path(r"dy_pipeline/data\示例客户\run_20260815_130550")
tracks = json.load(open(d / "tracks.json", encoding="utf-8"))["赛道"]
analysis = json.load(open(d / "analysis.json", encoding="utf-8"))["视频分析"]
cand = {v["aweme_id"]: v for v in json.load(open(d / "candidates.json", encoding="utf-8"))["视频"]}

rows = []
for a in analysis:
    v = cand.get(a.get("video_id"), {})
    rows.append({
        "video_id": a.get("video_id"),
        "标题": v.get("desc", "")[:60],
        "赛道倾向": a.get("赛道倾向", ""),
    })

assign_reps(tracks, rows, cand)
json.dump({"赛道": tracks}, open(d / "tracks.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("修复后:")
for t in tracks:
    names = [f"{cand.get(v,{}).get('desc','')[:18]}(赞{cand.get(v,{}).get('digg_count',0)})" for v in t.get("代表视频", [])]
    print(f"  {t['名称']}: {t['代表视频']}")
    for n in names:
        print(f"      - {n}")
