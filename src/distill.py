# -*- coding: utf-8 -*-
"""批量蒸馏：把全客户语料逐条拆成"风格蒸馏卡"→ 归纳成"爆款模式库"。

知识资产落盘：data/<客户>/distill/
  - 蒸馏卡/<video_id>.json   每条视频的风格蒸馏卡（钩子句式/语气/节奏/场景）
  - 模式库.json + 爆款模式库.md  跨视频归纳的爆款模式（生成时注入 prompt）

用法: python src/distill.py config/<客户>_需求卡.yaml [--limit N] [--force]
"""
import concurrent.futures as cf
import json
import logging
import sys
from pathlib import Path

from analyze import call_deepseek, get_api_key
from common import DATA, load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

DISTILL_PROMPT = """你是短视频爆款拆解专家。下面是一条爆款视频的完整逐字稿和结构化拆解。
请蒸馏出它的"风格指纹"，只输出 JSON：
{{
  "video_id": "...",
  "钩子公式化": "把前3秒钩子抽象成可复用句式，如：'打死别再[动作]，谁装谁后悔'",
  "语气特征": ["强否定", "清单体", "反问", "口语短句" 等，最多3个"],
  "代表性句式": ["2~3句最能代表该视频风格的句子（保留原话）"],
  "段落节奏": "段落结构+时间分配，如：钩子3s→逐条清单每条5s→收尾互动",
  "镜头场景": "该视频的拍摄场景与镜头方式（口播/实拍/展厅等）",
  "互动设计": "结尾如何引导互动（评论/点赞/收藏/私信）",
  "情绪曲线": "开头→中段→结尾的情绪变化",
  "可迁移结构": "剥离业务后，这个结构适合哪些行业复用"
}}

【逐字稿】
{transcript}

【结构化拆解】
{hint}"""


def distill_one(video: dict, transcript: str, analysis: dict, api_key: str) -> dict:
    hint = f"钩子:{analysis.get('钩子设计')}\n节奏:{analysis.get('叙事结构与节奏')}\n情绪:{analysis.get('情绪共鸣点')}\n爆点:{analysis.get('爆点归因')}"
    prompt = DISTILL_PROMPT.format(
        transcript=transcript[:2000] or "（无逐字稿）", hint=hint[:800] or "（无）")
    try:
        result = call_deepseek([{"role": "user", "content": prompt}], api_key, temperature=0.3)
        result["video_id"] = video["aweme_id"]
        result["标题"] = video.get("desc", "")[:40]
        result["账号"] = video.get("author", "")
        return result
    except Exception as e:
        log.error("[%s] 蒸馏失败: %s", video.get("aweme_id"), e)
        return None


def collect_corpus(card: dict) -> list:
    """聚合客户目录下所有 run 的 逐字稿+分析+候选，按 video_id 去重。"""
    base = DATA / str(card["客户"]).strip()
    items = {}
    for run_dir in sorted(base.glob("run_*")):
        cand = (read_json(run_dir / "selected_candidates.json")
                or read_json(run_dir / "candidates.json"))
        if not cand:
            continue
        by_id = {v["aweme_id"]: v for v in cand.get("视频", [])}
        analysis = {}
        an = read_json(run_dir / "analysis.json") or {}
        for a in an.get("视频分析", []):
            if "error" not in a:
                analysis[a.get("video_id")] = a
        for f in (run_dir / "transcripts").glob("*.txt") if (run_dir / "transcripts").exists() else []:
            vid = f.stem
            v = by_id.get(vid)
            if not v:
                continue
            items[vid] = {
                "video": v,
                "transcript": f.read_text(encoding="utf-8").strip(),
                "analysis": analysis.get(vid, {}),
            }
    return items


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--limit", type=int, default=0, help="只蒸馏前 N 条")
    ap.add_argument("--force", action="store_true", help="重蒸馏全部")
    ap.add_argument("--no-summary", action="store_true", help="跳过模式归纳")
    args = ap.parse_args()

    card = load_card(args.card)
    d = run_dir(card, resume=True)  # 蒸馏库是客户级资产，与具体 run 无关
    setup_log(d / "run.log")

    api_key = get_api_key()
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    out_dir = DATA / str(card["客户"]).strip() / "distill"
    cards_dir = out_dir / "蒸馏卡"
    cards_dir.mkdir(parents=True, exist_ok=True)

    corpus = collect_corpus(card)
    log.info("语料库聚合：%d 条视频（含逐字稿+分析）", len(corpus))

    todo = []
    for vid, it in corpus.items():
        card_file = cards_dir / f"{vid}.json"
        if card_file.exists() and not args.force:
            continue
        todo.append((vid, it))
    if args.limit:
        todo = todo[: args.limit]
    log.info("待蒸馏 %d 条（已蒸馏的自动跳过）", len(todo))

    done = 0
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {
            ex.submit(distill_one, it["video"], it["transcript"], it["analysis"], api_key): vid
            for vid, it in todo
        }
        for fut in cf.as_completed(futs):
            vid = futs[fut]
            result = fut.result()
            if result:
                write_json(cards_dir / f"{vid}.json", result)
                done += 1
                log.info("蒸馏完成 %d/%d: %s", done, len(todo), vid)
    log.info("蒸馏完成，共 %d 张蒸馏卡", done)

    if args.no_summary:
        return

    # ---- 模式归纳 ----
    cards = []
    for f in cards_dir.glob("*.json"):
        c = read_json(f)
        if c:
            cards.append({
                "video_id": c.get("video_id"),
                "标题": c.get("标题", "")[:30],
                "钩子公式化": c.get("钩子公式化", ""),
                "语气特征": c.get("语气特征", []),
                "段落节奏": c.get("段落节奏", ""),
                "镜头场景": c.get("镜头场景", ""),
                "互动设计": c.get("互动设计", ""),
            })
    if not cards:
        sys.exit("没有蒸馏卡，无法归纳模式")
    summary_prompt = f"""你是短视频爆款模式研究员。以下是 {len(cards)} 条爆款视频的风格蒸馏卡（JSON）。

【客户业务】{card.get('业务简介', '').strip()}
【客户卖点】{'、'.join(card.get('卖点') or [])}

请把相似风格的视频归纳为 6~10 个"爆款模式"，只输出 JSON：
{{"模式库":[
  {{"模式名":"如'避坑清单体'", "特征":"一句话概括该模式",
    "句式骨架":"该模式通用的句式模板，如'第一，千万别[做X]；第二，[正确做法]'",
    "语气要点":"语气/节奏特征",
    "镜头场景":"这类视频通常怎么拍",
    "互动设计":"结尾怎么引导互动",
    "代表视频":["video_id", ...],
    "客户适配":"改造成客户业务时的切入建议"}}
]}}
规则：模式之间要互斥（每条蒸馏卡只归入最像的一个模式）；句式骨架必须具体到能套用。

蒸馏卡数据：{json.dumps(cards, ensure_ascii=False)}"""
    log.info("归纳爆款模式库...")
    result = call_deepseek([{"role": "user", "content": summary_prompt}], api_key, temperature=0.3)
    write_json(out_dir / "模式库.json", result)

    lines = ["# 爆款模式库", "", f"- 来源：{len(cards)} 张蒸馏卡（客户全语料）", ""]
    for m in result.get("模式库", []):
        lines.append(f"## {m.get('模式名')}")
        lines.append(f"- 特征：{m.get('特征')}")
        lines.append(f"- 句式骨架：{m.get('句式骨架')}")
        lines.append(f"- 语气：{m.get('语气要点')}")
        lines.append(f"- 镜头：{m.get('镜头场景')}")
        lines.append(f"- 互动：{m.get('互动设计')}")
        lines.append(f"- 代表视频：{'、'.join(m.get('代表视频') or [])}")
        lines.append(f"- 客户适配：{m.get('客户适配')}")
        lines.append("")
    (out_dir / "爆款模式库.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("爆款模式库已生成: %s", out_dir / "爆款模式库.md")


if __name__ == "__main__":
    main()
