# -*- coding: utf-8 -*-
"""列出蒸馏卡的来源（证明全部是对标爆火视频，非生成的脚本）。"""
import json
from pathlib import Path

base = Path(r"dy_pipeline/data\示例客户\distill\蒸馏卡")
cards = []
for f in sorted(base.glob("*.json")):
    c = json.load(open(f, encoding="utf-8"))
    cards.append(c)

cards.sort(key=lambda c: -(c.get("video_id", "") == ""))
print(f"共 {len(cards)} 张蒸馏卡，来源明细：")
for c in cards:
    print(f"  {c.get('video_id','?')} | {c.get('账号','')} | {c.get('标题','')[:30]}")
    print(f"      钩子公式: {c.get('钩子公式化','')[:50]}")
