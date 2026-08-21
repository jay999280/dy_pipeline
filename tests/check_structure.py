# -*- coding: utf-8 -*-
"""抽查一条脚本的完整结构（时间戳/镜头/文案），评估模板化程度。"""
import json
from pathlib import Path

run = Path(r"dy_pipeline/data\示例客户\run_20260815_210319")
sc = json.load(open(run / "scripts.json", encoding="utf-8"))

# 每个赛道抽第 1 条 + 全部脚本的时间戳分布统计
for track, scripts in sc.items():
    s = scripts[0]
    print(f"===== {track}#1｜角度:{s.get('改编角度','')}")
    for sh in s.get("镜头", []):
        print(f"  [{sh.get('时间','?')}] {sh.get('画面','')[:30]} | {sh.get('文案','')[:36]}")
    # 时间戳统计
    times = [sh.get("时间", "") for sh in s.get("镜头", [])]
    print(f"  镜头数:{len(times)} | 时间戳: {times}")
