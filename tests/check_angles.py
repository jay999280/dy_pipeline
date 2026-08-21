# -*- coding: utf-8 -*-
import json
tracks = json.load(open(r"dy_pipeline/data\示例客户\run_20260815_130550\tracks.json", encoding="utf-8"))["赛道"]
for t in tracks:
    print(f"{t['名称']}: 角度={t.get('内容角度', '无')}")
    print(f"  代表={t.get('代表视频')}")
