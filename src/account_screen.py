# -*- coding: utf-8 -*-
"""① 账号粗筛：关键词搜索 → 聚合账号池 → 主页深挖 → AI 画像打分 → 人工确认。

产出：data/<客户>/<run>/账号候选清单.md（给人看）+ accounts_selected.json（待人工填写）
确认机制：本脚本跑完输出清单后退出码 2；用户确认后把选中的账号写入
accounts_selected.json 再重跑本脚本（或直接跑 run.py），已确认则跳过。
"""
import asyncio
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from analyze import call_deepseek, get_api_key
from collector import DouyinCollector
from common import load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

MAX_ACCOUNTS = 15          # 进入主页深挖的候选账号数
MIN_VIDEOS = 1             # 出现在搜索结果里少于 N 条视频的账号跳过（1=按最高赞纳池）
MIN_LIKES = 500            # 统计爆款数时按此点赞线


def aggregate_authors(summary: dict) -> list:
    """从搜索结果聚合账号统计。"""
    stats = defaultdict(lambda: {"视频数": 0, "最高赞": 0, "总赞": 0, "代表作": ""})
    for v in summary.get("视频", []):
        name = v.get("author", "")
        if not name:
            continue
        s = stats[name]
        s["视频数"] += 1
        s["最高赞"] = max(s["最高赞"], v.get("digg_count", 0))
        s["总赞"] += v.get("digg_count", 0)
        if v.get("digg_count", 0) >= s["最高赞"]:
            s["代表作"] = v.get("desc", "")[:40]
        s["sec_uid"] = v.get("sec_uid", "")
    return [
        {"昵称": k, **v}
        for k, v in stats.items()
        if v["视频数"] >= MIN_VIDEOS and v["sec_uid"]
    ]


def customer_profile_block(card: dict) -> str:
    """把客户画像渲染成 prompt 段落，供账号/视频粗筛匹配。"""
    profile = card.get("客户画像") or {}
    scenes = "、".join(str(s) for s in (profile.get("可拍摄场景") or [])) or "未提供"
    return (
        f"【客户专攻行业】{profile.get('专攻行业') or card.get('业务简介', '').strip()}\n"
        f"【客户品牌特点】{profile.get('品牌特点') or '未提供'}\n"
        f"【客户可拍摄场景】{scenes}\n"
        f"（选择对标时优先考虑：客户能否复现该账号/视频的拍摄场景与出镜方式）"
    )


def ai_profile(accounts: list, card: dict, api_key: str) -> list:
    """AI 给每个账号画像打分：垂直度/爆款力/业务相关度/场景适配度/人设匹配度。"""
    rows = [
        {"昵称": a["昵称"], "出现视频数": a["视频数"], "最高赞": a["最高赞"],
         "总赞": a["总赞"], "代表作": a["代表作"]}
        for a in accounts
    ]
    prompt = f"""你是短视频营销操盘手。以下是关键词搜索结果里聚合出的候选账号（{len(rows)} 个）。

【客户业务】{card.get('业务简介', '').strip()}
{customer_profile_block(card)}
【客户人设】{card.get('人设', '')}

请给每个账号打分并给出推荐理由，只输出 JSON：
{{"账号":[
  {{"昵称":"...", "垂直度":1到10, "爆款力":1到10, "业务相关度":1到10,
    "场景适配度":1到10, "人设匹配度":1到10,
    "综合分":1到10,
    "主要拍摄场景":"从该账号代表作推断（如：工厂实拍/展厅讲解/剧情演绎/口播车拍等）",
    "推荐理由":"一句话（该账号内容+场景+人设是否值得对标，结合客户可拍摄场景判断）",
    "建议动作":"深挖|观察|排除"}}
]}}
规则：
- 业务相关度：内容是否围绕客户专攻行业（见上文【客户专攻行业】，用其中的领域词判断，不要套用其他行业）
- 场景适配度：该账号的拍摄场景客户能否复现（工厂/展厅/客户家可复现；需要演员/特效/剧情的高分不了）
- 人设匹配度：出镜人设与客户（见【客户人设】）的相似度
- 综合分 = 垂直0.25 + 爆款0.25 + 业务相关0.20 + 场景0.15 + 人设0.15，四舍五入到 1 位小数
- 评分必须有区分度：不要都打 7 分——顶尖的给 9-10，明显弱的给 3-5 或建议排除，最多 3 个"深挖"
- 优先推荐：垂直+爆款+相关度+场景适配都高的账号；场景拍不出来的爆款账号只能列为观察

候选账号数据：{json.dumps(rows, ensure_ascii=False)}"""
    result = call_deepseek([{"role": "user", "content": prompt}], api_key, temperature=0.3)
    by_name = {a["昵称"]: a for a in accounts}
    out = []
    for r in result.get("账号", []):
        a = by_name.get(r.get("昵称"))
        if not a:
            continue
        a.update({
            "垂直度": r.get("垂直度"), "爆款力": r.get("爆款力"),
            "业务相关度": r.get("业务相关度"),
            "场景适配度": r.get("场景适配度"), "人设匹配度": r.get("人设匹配度"),
            "综合分": r.get("综合分"),
            "主要拍摄场景": r.get("主要拍摄场景", ""),
            "推荐理由": r.get("推荐理由", ""), "建议动作": r.get("建议动作", "观察"),
        })
        out.append(a)
    return out


def write_md(out_md: Path, accounts: list):
    lines = [
        "# 账号候选清单（第一轮人工筛选）",
        "",
        f"- 候选账号：{len(accounts)} 个（AI 粗筛，请人工确认后填写 accounts_selected.json）",
        "- 确认方法：把要分析的账号填入 `accounts_selected.json`（昵称+sec_uid 从下表复制），然后重跑本阶段",
        "",
        "| 昵称 | 搜索视频数 | 最高赞 | 主页作品数 | 主页爆款数 | 垂直 | 爆款 | 相关 | 场景 | 人设 | 综合 | 建议 | 主要场景 | 推荐理由 | sec_uid |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|",
    ]
    for a in sorted(accounts, key=lambda x: -(x.get("综合分") or (x.get("业务相关度") or 0) * 10 + (x.get("场景适配度") or 0) + (x.get("爆款力") or 0))):
        lines.append(
            f"| {a['昵称']} | {a['视频数']} | {a['最高赞']} | {a.get('主页作品数','-')} | "
            f"{a.get('主页爆款数','-')} | {a.get('垂直度','-')} | "
            f"{a.get('爆款力','-')} | {a.get('业务相关度','-')} | {a.get('场景适配度','-')} | "
            f"{a.get('人设匹配度','-')} | {a.get('综合分','-')} | {a.get('建议动作','-')} | {a.get('主要拍摄场景','')} | "
            f"{a.get('推荐理由','')} | `{a.get('sec_uid','')}` |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    log.info("账号候选清单已生成: %s", out_md)


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

    sel_file = d / "accounts_selected.json"
    if sel_file.exists() and read_json(sel_file):
        log.info("accounts_selected.json 已确认 %d 个账号，跳过账号粗筛", len(read_json(sel_file)))
        return

    api_key = get_api_key()
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    # ---- 1. 关键词搜索采集（有缓存则复用，便于调整打分维度后重打分） ----
    tmp = d / "_account_tmp"
    tmp.mkdir(exist_ok=True)
    search_file = tmp / "search.json"
    if search_file.exists():
        log.info("复用搜索采集缓存: %s", search_file)
        summary = read_json(search_file)
    else:
        search_card = dict(card)
        search_card["对标账号"] = []
        search_card["关键词"] = card.get("关键词") or []
        log.info("关键词搜索采集账号池...")
        summary = asyncio.run(DouyinCollector(search_card).run(search_file))
    accounts = aggregate_authors(summary)
    log.info("搜索聚合出 %d 个候选账号", len(accounts))
    if not accounts:
        log.warning("没有聚合到候选账号，检查关键词或登录态")
        write_json(d / "accounts_selected.json", [])
        sys.exit(2)
    accounts.sort(key=lambda a: -a["最高赞"])
    accounts = accounts[:MAX_ACCOUNTS]

    # ---- 2. 主页深挖：top 账号作品统计（有缓存则复用） ----
    profile_file = tmp / "profile.json"
    if profile_file.exists():
        log.info("复用主页采集缓存: %s", profile_file)
        prof = read_json(profile_file)
    else:
        prof_card = dict(card)
        prof_card["对标账号"] = [f"https://www.douyin.com/user/{a['sec_uid']}" for a in accounts]
        prof_card["关键词"] = []
        log.info("深挖 %d 个候选账号主页...", len(accounts))
        prof = asyncio.run(DouyinCollector(prof_card).run(profile_file))
    by_author = defaultdict(list)
    for v in prof.get("视频", []):
        if v["source"] == "profile":
            by_author[v["author"]].append(v)
    for a in accounts:
        vs = by_author.get(a["昵称"], [])
        a["主页作品数"] = len(vs)
        a["主页爆款数"] = sum(1 for v in vs if v.get("digg_count", 0) >= MIN_LIKES)
        if vs:
            a["主页最高赞"] = max(v.get("digg_count", 0) for v in vs)

    # ---- 3. AI 画像打分 ----
    accounts = ai_profile(accounts, card, api_key)
    write_md(d / "账号候选清单.md", accounts)
    # 预填空确认文件（占位，防误判为已确认）
    write_json(sel_file, [])
    log.info("== 第一轮人工筛选 ==")
    log.info("请查看 账号候选清单.md，把要分析的账号写入 accounts_selected.json（昵称+sec_uid），再重跑")
    sys.exit(2)


if __name__ == "__main__":
    main()
