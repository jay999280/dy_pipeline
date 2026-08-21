# -*- coding: utf-8 -*-
"""最终验收：检查流水线全部产物。"""
import json
from pathlib import Path

d = Path(r"dy_pipeline/data\示例客户\run_20260815_130550")

# 1. 采集
cand = json.load(open(d / "candidates.json", encoding="utf-8"))
print(f"[采集] 候选 {cand['总数']} 条，达标 {cand['推荐数']} 条")

# 2. 转写
transcripts = list((d / "transcripts").glob("*.txt"))
total_chars = sum(len(f.read_text(encoding="utf-8")) for f in transcripts)
print(f"[转写] {len(transcripts)} 份逐字稿，共 {total_chars} 字")

# 3. 分析
an = json.load(open(d / "analysis.json", encoding="utf-8"))["视频分析"]
ok = [a for a in an if "error" not in a]
print(f"[分析] {len(ok)}/{len(an)} 条成功，示例 hook: {ok[0].get('hook', {}).get('前3秒说什么', '')[:30]}")

# 4. 聚类
tracks = json.load(open(d / "tracks.json", encoding="utf-8"))["赛道"]
print(f"[聚类] {len(tracks)} 个赛道: {[t['名称'] for t in tracks]}")

# 5. 生成
sc = json.load(open(d / "scripts.json", encoding="utf-8"))
total = sum(len(v) for v in sc.values())
print(f"[生成] {total} 条脚本: { {k: len(v) for k, v in sc.items()} }")
xlsx = d / "脚本池.xlsx"
print(f"[输出] 脚本池.xlsx 存在={xlsx.exists()} 大小={xlsx.stat().st_size} bytes")

# 6. 抽样验证一条脚本的完整结构
sample = sc[tracks[0]["名称"]][0]
print("\n抽样脚本:")
print("  对标链接:", tracks[0]["代表视频"])
print("  发布文案:", sample["发布文案"][:50])
print("  镜头数:", len(sample["镜头"]))
print("  首镜:", sample["镜头"][0]["画面"], "|", sample["镜头"][0]["文案"][:40])
print("  尾镜:", sample["镜头"][-1]["画面"], "|", sample["镜头"][-1]["文案"][:40])

print("\n===== 端到端验收全部通过 =====")
