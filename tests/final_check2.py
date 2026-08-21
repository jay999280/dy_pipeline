# -*- coding: utf-8 -*-
"""最终综合验证：时长/链接/角度/同赛道钩子去重。"""
import json
from pathlib import Path

d = Path(r"dy_pipeline/data\示例客户\run_20260815_130550")
sc = json.load(open(d / "scripts.json", encoding="utf-8"))
cand = {v["aweme_id"]: v for v in json.load(open(d / "candidates.json", encoding="utf-8"))["视频"]}

bad = 0
for track, scripts in sc.items():
    hooks = set()
    for i, s in enumerate(scripts, 1):
        n = sum(len(sh.get("文案", "")) for sh in s.get("镜头", []))
        secs = n / 4
        h = (s.get("镜头") or [{}])[0].get("文案", "")[:12]
        hooks.add(h)
        vid = s.get("参考视频", "")
        ok = 30 <= secs <= 60 and vid in cand
        if not ok:
            bad += 1
        print(f"  [{track}#{i}] {secs:.0f}秒 | 链接有效={vid in cand} | 角度:{s.get('改编角度','')}")
    print(f"  同赛道钩子去重: {len(hooks)}/5")
print(f"=== 时长+链接全部达标: {bad == 0} (问题 {bad} 条) ===")
