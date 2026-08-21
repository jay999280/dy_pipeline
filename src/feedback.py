# -*- coding: utf-8 -*-
"""赛道复盘：录入试水期发布数据 → AI 复盘 → 聚焦建议 + 客户标签提炼。

试水期（第一个月）结束后的用法：
1. 把各条脚本的发布数据填入 data/<客户>/<run>/发布反馈.csv：
   赛道,脚本号,发布日期,播放量,点赞,评论,转发,咨询线索,备注
   （表头固定，行内容由你填；没有的字段留空）
2. 运行: python src/feedback.py config/<客户>_需求卡.yaml
3. 产出：赛道复盘报告.md（哪个赛道流量最好、为什么、下一阶段建议）
   + 需求卡更新建议（新提炼的客户标签/人设/卖点，供你确认后写回需求卡）

聚焦模式：把复盘结论的"主攻赛道"填进需求卡 `生成设置.主攻赛道`，
再跑 generate 就只生成该赛道的脚本。
"""
import csv
import json
import logging
import re
import sys
from pathlib import Path

from analyze import call_deepseek, get_api_key
from common import load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

CSV_HEADER = ["赛道", "脚本号", "发布日期", "播放量", "点赞", "评论", "转发", "咨询线索", "备注"]


def ensure_csv(d: Path, scripts_by_track: dict):
    """生成发布反馈 CSV 模板（带现有脚本清单，方便填数据）。"""
    out = d / "发布反馈.csv"
    if out.exists():
        return out
    rows = [CSV_HEADER]
    for track, scripts in scripts_by_track.items():
        for i in range(1, len(scripts) + 1):
            rows.append([track, i, "", "", "", "", "", "", ""])
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    log.info("发布反馈模板已生成: %s（请填写实际数据后重跑）", out)
    return out


def load_feedback(out_csv: Path) -> list:
    with open(out_csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if any((r.get(k) or "").strip() for k in ("播放量", "点赞", "咨询线索"))]


def summarize(rows: list) -> dict:
    by_track = {}
    for r in rows:
        t = (r.get("赛道") or "未知").strip()
        s = by_track.setdefault(t, {"条数": 0, "播放": 0, "点赞": 0, "评论": 0,
                                    "转发": 0, "咨询": 0})
        s["条数"] += 1
        for k, v in (("播放", "播放量"), ("点赞", "点赞"), ("评论", "评论"),
                     ("转发", "转发"), ("咨询", "咨询线索")):
            try:
                s[k] += int(float(r.get(v) or 0))
            except (TypeError, ValueError):
                pass
    return by_track


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    card = load_card(args.card)
    d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    api_key = get_api_key()
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    scripts_by_track = read_json(d / "scripts.json") or {}
    csv_path = ensure_csv(d, scripts_by_track)
    rows = load_feedback(csv_path)
    if not rows:
        log.info("发布反馈.csv 还没有数据，请先填写实际发布数据后重跑本模块")
        sys.exit(0)
    stats = summarize(rows)

    # ---- 钩子层归因：把每条脚本的钩子类型关联到发布数据 ----
    analysis = read_json(d / "analysis.json") or {}
    analysis_map = {a.get("video_id"): a for a in analysis.get("视频分析", [])}
    hook_map = {}
    for tname, scripts in scripts_by_track.items():
        for i, s in enumerate(scripts, 1):
            vid = str(s.get("参考视频", ""))
            hook_type = (analysis_map.get(vid, {}).get("钩子设计") or {}).get("类型", "未知")
            hook_map[f"{tname}#{i}"] = hook_type
    for r in rows:
        r["钩子类型"] = hook_map.get(f"{r.get('赛道','').strip()}#{r.get('脚本号','').strip()}", "未知")

    prompt = f"""你是短视频运营操盘手。客户试水期（约一个月）发布了多条脚本，以下是按赛道汇总的实测数据。

【客户业务】{card.get('业务简介', '').strip()}
【客户卖点】{'、'.join(card.get('卖点') or [])}
【客户画像】{json.dumps(card.get('客户画像', {}), ensure_ascii=False)}

【各赛道试水数据】
{json.dumps(stats, ensure_ascii=False, indent=2)}

【逐条原始数据】（含钩子类型，用于归因什么钩子/选题有效）
{json.dumps(rows, ensure_ascii=False, indent=2)}

请输出复盘结论，只输出 JSON：
{{
  "赛道复盘": [
    {{"赛道":"...", "表现": "好|中|差", "数据表现":"播放/互动/咨询等量化总结",
      "内容优势":"这个赛道内容为什么表现这样（钩子/结构/题材）",
      "优化建议":"下阶段怎么改"}}
  ],
  "主攻赛道": "数据最好、最值得专攻的赛道名",
  "放弃赛道": ["建议停掉的赛道"],
  "有效钩子": ["数据验证过表现好的钩子类型（对照逐条的钩子类型与播放/互动数据），如'痛点型'、'悬念型'"],
  "人设标签提炼": ["从数据反馈中提炼出的客户人设新标签，如'靠谱直说'、'现场实测'"],
  "卖点强化": ["数据验证过的卖点，后续脚本应强化"],
  "需求卡更新建议": "如何更新客户画像/关键词/排除规则（一段话）"
}}
注意：播放量看均值而非总量；咨询线索是最硬指标（直接转化）；互动率=点赞/播放；
钩子归因：把播放/互动表现好的条目按钩子类型分组，得出哪些钩子有效、哪些无效。"""

    result = call_deepseek([{"role": "user", "content": prompt}], api_key, temperature=0.3)
    write_json(d / "赛道复盘.json", result)

    lines = [
        "# 赛道复盘报告（试水期）",
        "",
        f"- 已录入 {len(rows)} 条发布数据，覆盖 {len(stats)} 个赛道",
        "",
        "## 各赛道数据",
        "",
        "| 赛道 | 条数 | 播放 | 点赞 | 评论 | 转发 | 咨询线索 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for t, s in stats.items():
        lines.append(f"| {t} | {s['条数']} | {s['播放']} | {s['点赞']} | {s['评论']} | "
                     f"{s['转发']} | {s['咨询']} |")
    lines.append("\n## AI 复盘结论\n")
    for t in result.get("赛道复盘", []):
        lines.append(f"### {t.get('赛道')}（{t.get('表现')}）")
        lines.append(f"- 数据：{t.get('数据表现')}")
        lines.append(f"- 优势：{t.get('内容优势')}")
        lines.append(f"- 优化：{t.get('优化建议')}")
    lines.append(f"\n## 主攻赛道：**{result.get('主攻赛道', '?')}**")
    lines.append(f"放弃赛道：{'、'.join(result.get('放弃赛道') or [])}")
    lines.append("\n## 有效钩子（数据验证过）")
    for h in result.get("有效钩子", []):
        lines.append(f"- {h}")
    lines.append("\n## 人设标签提炼")
    for tag in result.get("人设标签提炼", []):
        lines.append(f"- {tag}")
    lines.append("\n## 卖点强化")
    for p in result.get("卖点强化", []):
        lines.append(f"- {p}")
    lines.append(f"\n## 需求卡更新建议\n{result.get('需求卡更新建议', '')}")
    lines.append("\n## 下一步\n把主攻赛道名填入需求卡 `生成设置.主攻赛道`，重跑 generate 即聚焦该赛道。")
    (d / "赛道复盘报告.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("赛道复盘报告已生成: %s", d / "赛道复盘报告.md")


if __name__ == "__main__":
    main()
