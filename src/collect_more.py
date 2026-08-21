# -*- coding: utf-8 -*-
"""语料扩充：采集对标账号更多作品 → 高赞筛选 → 生成独立语料 run 目录。

产出：data/<客户>/run_corpus_ext/candidates.json（recommend=高赞候选）
之后: python src/transcribe.py card --run data/.../run_corpus_ext
      python src/analyze.py    card --run data/.../run_corpus_ext
      python src/distill.py    card   （自动扫到 run_corpus_ext 增量蒸馏）
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from collector import DouyinCollector
from common import DATA, load_card, read_json, setup_log, write_json

log = logging.getLogger(__name__)

# 默认阈值（可在需求卡 采集设置 下覆盖）
DEFAULT_MAX_PER_ACCOUNT = 40   # 每个账号最多采集条数
DEFAULT_MIN_LIKES = 300        # 进入转写候选的最低点赞
DEFAULT_MAX_TRANSCRIBE = 30    # 转写候选上限（按点赞取 top）


def load_ext_accounts(card: dict) -> list:
    """语料扩充账号来源（优先级从高到低）：
    1. 需求卡 `语料扩充账号`（列表，每项 {昵称, sec_uid}）
    2. 跨 run 沉淀的账号池 data/<客户>/account_pool.json（历史人工确认账号）
    3. 都没有 → 返回空列表，由调用方告警跳过。
    """
    ext = card.get("语料扩充账号") or []
    accounts = []
    for a in ext:
        if isinstance(a, dict) and a.get("sec_uid"):
            accounts.append((str(a.get("昵称", "")), str(a["sec_uid"])))
        elif isinstance(a, str) and a.strip():
            accounts.append(("", a.strip()))
    if accounts:
        return accounts

    pool = read_json(DATA / str(card["客户"]).strip() / "account_pool.json") or []
    accounts = [(str(a.get("昵称", "")), str(a["sec_uid"]))
                for a in pool if a.get("sec_uid")]
    if accounts:
        log.info("从 account_pool.json 复用 %d 个历史确认账号", len(accounts))
    return accounts


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    args = ap.parse_args()

    card = load_card(args.card)
    d = DATA / str(card["客户"]).strip() / "run_corpus_ext"
    d.mkdir(parents=True, exist_ok=True)
    setup_log(d / "run.log")

    out = d / "candidates.json"
    if out.exists():
        log.info("candidates.json 已存在，跳过采集（删除文件可重采）")
        return

    accounts = load_ext_accounts(card)
    if not accounts:
        log.warning("需求卡无 `语料扩充账号` 且无 account_pool.json，跳过语料扩充")
        return

    # 阈值：需求卡 采集设置 可覆盖
    cs = card.get("采集设置") or {}
    max_per = int(cs.get("语料扩充每号条数", DEFAULT_MAX_PER_ACCOUNT))
    min_likes = int(cs.get("语料扩充最低赞", DEFAULT_MIN_LIKES))
    max_trans = int(cs.get("语料扩充转写上限", DEFAULT_MAX_TRANSCRIBE))

    prof_card = dict(card)
    prof_card["对标账号"] = [f"https://www.douyin.com/user/{uid}" for _, uid in accounts]
    prof_card["关键词"] = []
    prof_card["采集设置"] = dict(cs)
    prof_card["采集设置"]["每个来源最多视频数"] = max_per
    prof_card["采集设置"]["滚动上限"] = 30
    log.info("采集 %d 个对标账号的更多作品（每号最多 %d 条）...",
             len(accounts), max_per)
    prof = asyncio.run(DouyinCollector(prof_card).run(out))

    # 高赞筛选 → 转写候选
    items = [v for v in prof.get("视频", []) if v.get("digg_count", 0) >= min_likes]
    items.sort(key=lambda v: -v.get("digg_count", 0))
    for v in items[:max_trans]:
        v["recommend"] = True
    summary = {
        "客户": card.get("客户"),
        "来源": "语料扩充（对标账号更多作品）",
        "总数": len(prof.get("视频", [])),
        "推荐数": min(len(items), max_trans),
        "视频": items[:max_trans],
    }
    write_json(out, summary)
    log.info("采集 %d 条，≥%d 赞 %d 条，转写候选 top %d", len(summary["视频"]),
             min_likes, len(items), len(summary["视频"]))


if __name__ == "__main__":
    main()
