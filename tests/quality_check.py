# -*- coding: utf-8 -*-
"""质量对比：每条脚本的钩子 vs 参考视频开头，看差异化和风格模仿。"""
import json
from pathlib import Path

d = Path(r"dy_pipeline/data\示例客户\run_20260815_130550")
sc = json.load(open(d / "scripts.json", encoding="utf-8"))
cand = {v["aweme_id"]: v for v in json.load(open(d / "candidates.json", encoding="utf-8"))["视频"]}

print("=" * 70)
for track, scripts in sc.items():
    print(f"\n########## 赛道：{track} ##########")
    for i, s in enumerate(scripts, 1):
        vid = s.get("参考视频", "")
        ref = cand.get(vid, {})
        tf = d / "transcripts" / f"{vid}.txt"
        ref_head = tf.read_text(encoding="utf-8")[:50].replace("\n", "") if tf.exists() else "(无逐字稿)"
        shots = s.get("镜头", [])
        hook = shots[0]["文案"][:45] if shots else ""
        n = sum(len(sh.get("文案", "")) for sh in shots)
        print(f"\n  脚本{i}｜角度:{s.get('改编角度','')}｜{n}字≈{n/4:.0f}秒")
        print(f"    我的钩子: {hook}")
        print(f"    参考开头: {ref_head}")
        print(f"    参考视频: {vid} {ref.get('desc','')[:18]}")
