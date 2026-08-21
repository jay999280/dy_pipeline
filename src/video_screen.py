# -*- coding: utf-8 -*-
"""② 视频粗筛：已确认账号 → 主页作品 → 互动排序 → AI 打分 → 人工确认。

产出：爆款视频候选清单.md（给人看）+ videos_selected.json（待人工填写）
确认后重跑：把选中的视频组装成 selected_candidates.json，供转写/分析/聚类/生成使用。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from analyze import call_deepseek, get_api_key
from collector import DouyinCollector
from common import load_card, read_json, run_dir, setup_log, write_json
from account_screen import customer_profile_block

log = logging.getLogger(__name__)

PER_ACCOUNT = 10   # 每个账号进入候选的 top 视频数


def ai_score(videos: list, card: dict, api_key: str) -> list:
    """AI 给每条候选视频打分：爆款指数/业务相关度/可改编性/场景可拍性/建议。"""
    rows = [
        {"video_id": v["aweme_id"], "标题": v.get("desc", "")[:50],
         "点赞": v.get("digg_count", 0), "评论": v.get("comment_count", 0),
         "转发": v.get("share_count", 0), "账号": v.get("author", "")}
        for v in videos
    ]
    prompt = f"""你是短视频操盘手。以下是已确认对标账号的候选爆款视频（{len(rows)} 条）。

【客户业务】{card.get('业务简介', '').strip()}
{customer_profile_block(card)}
【排除规则】{card.get('排除规则', '')}

请给每条视频打分，只输出 JSON：
{{"视频":[
  {{"video_id":"...", "爆款指数":1到10, "业务相关度":1到5, "可改编性":1到5,
    "场景可拍性":1到5,
    "推荐理由":"一句话（这条为什么爆/客户能否拍出类似画面/能否改编成客户内容）",
    "建议":"入选|候选|排除"}}
]}}
规则：
- 爆款指数：点赞/评论/转发越高越爆，评论高说明争议互动强
- 业务相关度：内容是否围绕客户专攻行业（见上文【客户专攻行业】，用其中的领域词判断，不要套用其他行业）
- 场景可拍性：画面场景客户能否复现（展厅/工厂/安装现场/客户家可复现；演员剧情/特效/外部素材高分不了）
- 可改编性：是否有清晰结构/钩子/口播（标题能看出叙事则高）
- 排除：与业务无关的泛内容、纯广告搬运、无可复用结构、场景客户拍不出来的

候选视频数据：{json.dumps(rows, ensure_ascii=False)}"""
    result = call_deepseek([{"role": "user", "content": prompt}], api_key, temperature=0.3)
    by_id = {v["aweme_id"]: v for v in videos}
    out = []
    for r in result.get("视频", []):
        v = by_id.get(str(r.get("video_id")))
        if not v:
            continue
        v.update({
            "爆款指数": r.get("爆款指数"), "业务相关度": r.get("业务相关度"),
            "可改编性": r.get("可改编性"), "场景可拍性": r.get("场景可拍性"),
            "推荐理由": r.get("推荐理由", ""),
            "建议": r.get("建议", "候选"),
        })
        out.append(v)
    return out


def write_md(out_md: Path, videos: list):
    lines = [
        "# 爆款视频候选清单（第二轮人工筛选）",
        "",
        f"- 候选视频：{len(videos)} 条（AI 粗筛，请人工确认后填写 videos_selected.json）",
        "- 确认方法：把要深度拆解的 video_id 填入 `videos_selected.json`，然后重跑本阶段",
        "",
        "| 账号 | 标题 | 点赞 | 评论 | 爆款 | 相关 | 可改编 | 场景可拍 | 建议 | 理由 | 链接 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for v in sorted(videos, key=lambda x: -((x.get("爆款指数") or 0) * 10
                                           + (x.get("业务相关度") or 0) * 5
                                           + (x.get("场景可拍性") or 0) * 5)):
        lines.append(
            f"| {v.get('author','')} | {v.get('desc','')[:34]} | {v.get('digg_count',0)} | "
            f"{v.get('comment_count',0)} | {v.get('爆款指数','-')} | "
            f"{v.get('业务相关度','-')} | {v.get('可改编性','-')} | {v.get('场景可拍性','-')} | "
            f"{v.get('建议','-')} | {v.get('推荐理由','')} | https://www.douyin.com/video/{v['aweme_id']} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    log.info("爆款视频候选清单已生成: %s", out_md)


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

    sel_file = d / "videos_selected.json"

    # ---- 确认文件已填 → 组装 selected_candidates.json ----
    selected = read_json(sel_file)
    if selected:
        cand = read_json(d / "candidates.json") or {}
        by_id = {v["aweme_id"]: v for v in cand.get("视频", [])}
        want = [str(x) for x in selected]
        picked = [by_id[x] for x in want if x in by_id]
        # 主页作品补充（搜索可能没有这些视频的完整数据）
        prof = read_json(d / "_account_tmp" / "profile.json") or {}
        by_id.update({v["aweme_id"]: v for v in prof.get("视频", [])})
        picked = [by_id[x] for x in want if x in by_id]
        picked.sort(key=lambda v: -v.get("digg_count", 0))
        if not picked:
            sys.exit("videos_selected.json 中的 video_id 未在采集数据中找到")
        for v in picked:  # 人工选中的一律视为推荐，转写/分析不做二次过滤
            v["recommend"] = True
        summary = {
            "客户": card.get("客户"),
            "来源": "第二轮人工筛选确认",
            "总数": len(picked),
            "推荐数": len(picked),
            "视频": picked,
        }
        write_json(d / "selected_candidates.json", summary)
        log.info("已确认 %d 条视频，selected_candidates.json 已生成", len(picked))
        return

    # ---- 未确认：采集已选账号主页 → AI 打分 → 输出清单 ----
    accounts = read_json(d / "accounts_selected.json")
    if not accounts:
        sys.exit("accounts_selected.json 为空，请先完成第一轮账号筛选")

    api_key = get_api_key()
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    prof_card = dict(card)
    prof_card["对标账号"] = [
        f"https://www.douyin.com/user/{a['sec_uid']}" for a in accounts if a.get("sec_uid")
    ]
    prof_card["关键词"] = []
    tmp = d / "_account_tmp"
    tmp.mkdir(exist_ok=True)
    log.info("采集 %d 个已确认账号的主页作品...", len(prof_card["对标账号"]))
    prof = asyncio.run(DouyinCollector(prof_card).run(tmp / "profile.json"))

    by_author = {}
    for v in prof.get("视频", []):
        if v["source"] == "profile":
            by_author.setdefault(v["author"], []).append(v)
    candidates = []
    for author, vs in by_author.items():
        vs.sort(key=lambda v: -v.get("digg_count", 0))
        candidates.extend(vs[:PER_ACCOUNT])
    log.info("每个账号取 top %d，共 %d 条候选视频", PER_ACCOUNT, len(candidates))
    if not candidates:
        log.warning("主页没有采到视频（可能账号变更或被风控）")
        sys.exit(2)

    candidates = ai_score(candidates, card, api_key)
    write_md(d / "爆款视频候选清单.md", candidates)
    write_json(sel_file, [])
    log.info("== 第二轮人工筛选 ==")
    log.info("请查看 爆款视频候选清单.md，把要拆解的 video_id 写入 videos_selected.json，再重跑")
    sys.exit(2)


if __name__ == "__main__":
    main()
