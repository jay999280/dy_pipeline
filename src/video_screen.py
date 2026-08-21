# -*- coding: utf-8 -*-
"""② 视频粗筛：已确认账号 → 主页作品 → 量化预筛 + 五维匹配度 → 人工确认。

产出：爆款视频候选清单.md（给人看，模板 A）+ videos_selected.json（待人工填写）
确认后重跑：把选中的视频组装成 selected_candidates.json，供转写/分析/聚类/生成使用。
"""
import asyncio
import datetime
import json
import logging
import statistics
import sys
from pathlib import Path

from analyze import call_deepseek, get_api_key
from collector import DouyinCollector
from common import load_card, read_json, run_dir, setup_log, write_json
from account_screen import customer_profile_block, suggest_keywords

log = logging.getLogger(__name__)

PER_ACCOUNT = 10   # 每个账号进入候选的 top 视频数


# ---------- 第一层：量化预筛（确定性计算，不调 LLM） ----------
def _median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def quantitative_prescreen(videos: list, by_author: dict, card: dict) -> list:
    """给每条候选视频计算量化指标：爆款系数/互动率/评论赞比/发布月龄，并打硬否决标记。

    - 爆款系数 = 该视频赞 ÷ 该账号作品中位数赞（≥阈值视为账号级爆款）
    - 互动率 = (赞+评+转) ÷ 播放（播放缺失时记 None，不否决）
    - 评论赞比 = 评论 ÷ 赞（争议/讨论度信号，加分项）
    - 发布月龄 = 距今月数（超硬门槛月数需人工确认）
    """
    cs = card.get("筛选设置") or {}
    burst_thr = float(cs.get("爆款系数阈值", 3))
    eng_thr = float(cs.get("互动率阈值", 0.03))
    fresh_block = int(cs.get("发布时间硬门槛月数", 24))
    now = datetime.datetime.now()
    for v in videos:
        author = v.get("author", "")
        med = _median([x.get("digg_count", 0) for x in by_author.get(author, [])]) or 1.0
        digg = v.get("digg_count", 0) or 0
        v["爆款系数"] = round(digg / med, 2)
        play = v.get("play_count", 0) or 0
        inter = digg + (v.get("comment_count", 0) or 0) + (v.get("share_count", 0) or 0)
        v["互动率"] = round(inter / play, 4) if play else None
        v["评论赞比"] = round((v.get("comment_count", 0) or 0) / digg, 4) if digg else 0.0
        ct = v.get("create_time", 0) or 0
        v["发布月龄"] = round((now - datetime.datetime.fromtimestamp(ct)).days / 30, 1) if ct else None
        # 硬否决标记：仅"发布过旧"硬否决；其余指标作为打分输入与展示（候选已是账号 top，避免过滤过狠）
        v["预筛否决"] = bool(ct and v["发布月龄"] > fresh_block)
        v["爆款达标"] = v["爆款系数"] >= burst_thr
        v["互动达标"] = (v["互动率"] is not None and v["互动率"] >= eng_thr)
    return videos


# ---------- 第二层：AI 五维匹配度（1-10 分 + 依据） ----------
def ai_score(videos: list, card: dict, api_key: str) -> list:
    """五维匹配度：定位契合/受众重合/场景可复现/人设相似/改编潜力，各 1-10 + 依据 + 加权综合。"""
    rows = [
        {"video_id": v["aweme_id"], "标题": v.get("desc", "")[:50],
         "点赞": v.get("digg_count", 0), "评论": v.get("comment_count", 0),
         "转发": v.get("share_count", 0), "播放": v.get("play_count", 0) or None,
         "爆款系数": v.get("爆款系数"), "互动率": v.get("互动率"),
         "评论赞比": v.get("评论赞比"), "发布月龄": v.get("发布月龄"),
         "账号": v.get("author", "")}
        for v in videos
    ]
    prompt = f"""你是短视频操盘手。以下是已确认对标账号的候选爆款视频（{len(rows)} 条），含量化指标。

【客户业务】{card.get('业务简介', '').strip()}
{customer_profile_block(card)}
【客户人设】{card.get('人设', '')}
【目标客户】{card.get('目标客户', '')}
【排除规则】{card.get('排除规则', '')}

请给每条视频做五维匹配度评分（每维 1-10 分 + 一句依据），只输出 JSON：
{{"视频":[
  {{"video_id":"...",
    "定位契合度":1到10, "定位依据":"一句话",
    "受众重合度":1到10, "受众依据":"一句话",
    "场景可复现度":1到10, "场景依据":"一句话",
    "人设相似度":1到10, "人设依据":"一句话",
    "改编潜力":1到10, "改编依据":"一句话",
    "综合分":1到10,
    "推荐理由":"一句话（数据依据+逻辑依据）",
    "建议":"入选|候选|排除"}}
]}}
评分规则：
- 定位契合度：视频内容领域是否围绕客户专攻行业（见上文【客户专攻行业】，用其中的领域词判断）
- 受众重合度：视频面向人群与客户目标客户的匹配度（从内容与标题推断受众）
- 场景可复现度：画面场景客户能否复现（见【客户可拍摄场景】；演员剧情/特效/外部素材高分不了）
- 人设相似度：出镜人设与客户人设的相似度
- 改编潜力：结构清晰度/口播质量/可迁移性；量化指标作为客观参考——爆款系数≥3 或 互动率≥3% 或 评论赞比≥2% 任一达标即视为已验证爆款，改编潜力可上调
- 综合分 = 定位0.30 + 受众0.20 + 场景0.20 + 人设0.15 + 改编0.15，四舍五入到 1 位小数
- 评分必须有区分度：同批评分标准差 ≥1.0，不要都打 7 分——顶尖给 9-10，明显弱的给 3-5 或建议排除
- 发布月龄 >12 的降权（内容可能过时）；排除：与业务无关、纯广告搬运、无可复用结构、场景拍不出的

候选视频数据：{json.dumps(rows, ensure_ascii=False)}"""
    result = call_deepseek([{"role": "user", "content": prompt}], api_key, temperature=0.3)
    by_id = {v["aweme_id"]: v for v in videos}
    out = []
    for r in result.get("视频", []):
        v = by_id.get(str(r.get("video_id")))
        if not v:
            continue
        v.update({
            "定位契合度": r.get("定位契合度"), "定位依据": r.get("定位依据", ""),
            "受众重合度": r.get("受众重合度"), "受众依据": r.get("受众依据", ""),
            "场景可复现度": r.get("场景可复现度"), "场景依据": r.get("场景依据", ""),
            "人设相似度": r.get("人设相似度"), "人设依据": r.get("人设依据", ""),
            "改编潜力": r.get("改编潜力"), "改编依据": r.get("改编依据", ""),
            "综合分": r.get("综合分"),
            "推荐理由": r.get("推荐理由", ""),
            "建议": r.get("建议", "候选"),
        })
        out.append(v)
    return out


# ---------- 评估标准 A：区分度 / 硬门槛执行率 ----------
def evaluate_screen(videos: list) -> dict:
    scores = [v.get("综合分") for v in videos if isinstance(v.get("综合分"), (int, float))]
    return {
        "候选数": len(videos),
        "综合分标准差": round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0.0,
        "硬否决数": sum(1 for v in videos if v.get("预筛否决")),
        "建议入选数": sum(1 for v in videos if v.get("建议") == "入选"),
    }


def write_md(out_md: Path, videos: list, card: dict):
    ev = evaluate_screen(videos)
    lines = [
        "# 爆款视频候选清单（第二轮人工筛选）",
        "",
        f"- 候选视频：{ev['候选数']} 条（AI 粗筛，请人工确认后填写 videos_selected.json）",
        f"- 筛选标准：爆款系数≥{card.get('筛选设置', {}).get('爆款系数阈值', 3)}｜互动率≥{int((card.get('筛选设置', {}).get('互动率阈值', 0.03) or 0.03) * 100)}%（播放缺失不计）｜评论赞比≥2% 加分｜完播率平台不暴露，以时长+互动率代理",
        f"- 区分度：综合分标准差 {ev['综合分标准差']}（≥1.0 为合格）｜建议入选 {ev['建议入选数']} 条",
        "- 确认方法：把要深度拆解的 video_id 填入 `videos_selected.json`，然后重跑本阶段",
        "",
        "| 排名 | 账号 | 标题 | 赞 | 评 | 互动率 | 爆款系数 | 定位 | 受众 | 场景 | 人设 | 改编 | 综合分 | 建议 | 推荐理由 | 链接 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    ranked = sorted(videos, key=lambda x: -(x.get("综合分") or 0))
    for i, v in enumerate(ranked, 1):
        eng = f"{v.get('互动率')*100:.1f}%" if v.get("互动率") is not None else "缺"
        lines.append(
            f"| {i} | {v.get('author','')} | {v.get('desc','')[:26]} | {v.get('digg_count',0)} | "
            f"{v.get('comment_count',0)} | {eng} | {v.get('爆款系数','-')} | "
            f"{v.get('定位契合度','-')} | {v.get('受众重合度','-')} | {v.get('场景可复现度','-')} | "
            f"{v.get('人设相似度','-')} | {v.get('改编潜力','-')} | {v.get('综合分','-')} | "
            f"{v.get('建议','-')} | {v.get('推荐理由','')} | https://www.douyin.com/video/{v['aweme_id']} |"
        )
    # 逐条匹配度分析（TOP 5）
    lines.append("\n## 逐条匹配度分析（TOP 5）\n")
    for i, v in enumerate(ranked[:5], 1):
        lines.append(f"### 第 {i} 名：{v.get('desc','')[:40]}")
        lines.append(f"- 定位契合 {v.get('定位契合度','-')}/10：{v.get('定位依据','')}")
        lines.append(f"- 受众重合 {v.get('受众重合度','-')}/10：{v.get('受众依据','')}")
        lines.append(f"- 场景可复现 {v.get('场景可复现度','-')}/10：{v.get('场景依据','')}")
        lines.append(f"- 人设相似 {v.get('人设相似度','-')}/10：{v.get('人设依据','')}")
        lines.append(f"- 改编潜力 {v.get('改编潜力','-')}/10：{v.get('改编依据','')}")
        lines.append(f"- **综合 {v.get('综合分','-')}/10｜{v.get('推荐理由','')}**")
        lines.append(f"- 链接：https://www.douyin.com/video/{v['aweme_id']}\n")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    log.info("爆款视频候选清单已生成: %s（区分度 %.2f）", out_md, ev["综合分标准差"])


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
        prof = read_json(d / "_account_tmp" / "profile.json") or {}
        by_id.update({v["aweme_id"]: v for v in prof.get("视频", [])})
        picked = [by_id[x] for x in want if x in by_id]
        picked.sort(key=lambda v: -v.get("digg_count", 0))
        if not picked:
            sys.exit("videos_selected.json 中的 video_id 未在采集数据中找到")
        for v in picked:
            v["recommend"] = True
        # 附加对照组（同账号低互动作品）：进转写/分析/蒸馏，供爆/非爆增量对照；聚类/生成会过滤
        control = read_json(d / "对照视频.json") or {}
        for v in control.get("视频", []):
            v["对照"] = True
            v["recommend"] = True
        picked += control.get("视频", [])
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

    # ---- 未确认：搜索驱动模式（像人刷视频）或账号模式 ----
    accounts = read_json(d / "accounts_selected.json")
    if not accounts:
        # 搜索驱动模式：不强制先选账号，直接按关键词不断刷爆款视频，逐条评估后人工选视频
        log.info("无已确认账号 → 搜索驱动模式：按关键词像人一样刷爆款视频")
        api_key = get_api_key()
        if not api_key:
            sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")
        cs = card.get("采集设置") or {}
        search_card = dict(card)
        search_card["对标账号"] = []
        search_card["关键词"] = card.get("关键词") or []
        search_card["采集设置"] = dict(cs)
        search_card["采集设置"]["每个来源最多视频数"] = int(cs.get("搜索刷视频每关键词上限", 50))
        search_card["采集设置"]["滚动上限"] = int(cs.get("搜索刷视频滚动上限", 30))
        kws = search_card["关键词"]
        if not kws:
            sys.exit("搜索驱动模式需要需求卡 关键词 非空")
        log.info("搜索刷视频：%d 个关键词，每关键词滚动上限 %d",
                 len(kws), search_card["采集设置"]["滚动上限"])
        search = asyncio.run(DouyinCollector(search_card).run(d / "candidates.json"))
        videos = search.get("视频", [])
        if not videos:
            log.warning("搜索没有采到视频（检查关键词或登录态）")
            sys.exit(2)
        # 量化预筛 + AI 五维打分（同账号视频少时爆款系数仅供参考）
        by_author = {}
        for v in videos:
            by_author.setdefault(v.get("author", ""), []).append(v)
        candidates = quantitative_prescreen(videos, by_author, card)
        candidates = [v for v in candidates if not v.get("预筛否决")]
        candidates = ai_score(candidates, card, api_key)
        # 关键词滚雪球：从刷到的视频标题提炼补充关键词（人工采纳后填回需求卡二轮刷）
        kw_file = d / "关键词建议.txt"
        if not kw_file.exists():
            sugg = suggest_keywords(search, card, api_key)
            if sugg:
                kw_file.write_text("补充关键词建议（可填回需求卡 关键词 字段后二轮刷视频）：\n"
                                   + "\n".join(f"- {k}" for k in sugg), encoding="utf-8")
                log.info("关键词建议已生成: %s（%d 个）", kw_file.name, len(sugg))
        write_md(d / "爆款视频候选清单.md", candidates, card)
        write_json(sel_file, [])
        log.info("== 视频筛选（搜索驱动）==")
        log.info("请查看 爆款视频候选清单.md，把要拆解的 video_id 写入 videos_selected.json，再重跑")
        sys.exit(2)

    # 账号模式：已确认账号 → 主页作品深挖
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
    control = []
    for author, vs in by_author.items():
        vs.sort(key=lambda v: -v.get("digg_count", 0))
        candidates.extend(vs[:PER_ACCOUNT])
        # 对照组：同账号低互动作品（中位数以下），供爆/非爆增量对照分析
        med = _median([v.get("digg_count", 0) for v in vs])
        low = [v for v in vs if v.get("digg_count", 0) < med]
        control.extend(low[:2])
    if control:
        for v in control:
            v["对照"] = True
        write_json(d / "对照视频.json", {"客户": card.get("客户"), "视频": control})
        log.info("记录 %d 条对照组（同账号低互动作品）", len(control))
    log.info("每个账号取 top %d，共 %d 条候选视频", PER_ACCOUNT, len(candidates))
    if not candidates:
        log.warning("主页没有采到视频（可能账号变更或被风控）")
        sys.exit(2)

    # 量化预筛（确定性）+ AI 五维打分
    candidates = quantitative_prescreen(candidates, by_author, card)
    candidates = [v for v in candidates if not v.get("预筛否决")]
    candidates = ai_score(candidates, card, api_key)
    write_md(d / "爆款视频候选清单.md", candidates, card)
    write_json(sel_file, [])
    log.info("== 第二轮人工筛选 ==")
    log.info("请查看 爆款视频候选清单.md，把要拆解的 video_id 写入 videos_selected.json，再重跑")
    sys.exit(2)


if __name__ == "__main__":
    main()
