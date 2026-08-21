# -*- coding: utf-8 -*-
"""验证指定 run 目录的脚本质量。用法: python verify_run.py <run目录>"""
import json
import sys
from pathlib import Path

run = Path(sys.argv[1] if len(sys.argv) > 1 else r"dy_pipeline/data\示例客户\run_20260815_210319")
sc = json.load(open(run / "scripts.json", encoding="utf-8"))
cand = {v["aweme_id"]: v for v in json.load(open(run / "selected_candidates.json", encoding="utf-8"))["视频"]}

bad = 0
for track, scripts in sc.items():
    hooks = set()
    for i, s in enumerate(scripts, 1):
        n = sum(len(sh.get("文案", "")) for sh in s.get("镜头", []))
        secs = n / 4
        h = (s.get("镜头") or [{}])[0].get("文案", "")[:14]
        hooks.add(h)
        vid = s.get("参考视频", "")
        ref = cand.get(vid, {})
        ok = 30 <= secs <= 60 and bool(ref)
        if not ok:
            bad += 1
        print(f"  [{track}#{i}] {secs:.0f}秒 | 参考={ref.get('author','?')} | 角度:{s.get('改编角度','')}")
        print(f"      钩子: {h}...")
        print(f"      参考标题: {ref.get('desc','')[:40]}")
    print(f"  {track} 同赛道钩子去重: {len(hooks)}/5")
print(f"=== 全部达标: {bad == 0} (问题 {bad} 条) ===")
