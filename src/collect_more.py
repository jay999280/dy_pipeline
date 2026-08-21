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
from common import DATA, load_card, setup_log, write_json

log = logging.getLogger(__name__)

EXT_ACCOUNTS = [
    ("示例账号1", "MS4wLjABAAAAexample"),
    ("示例账号2", "MS4wLjABAAAAexample"),
    ("示例账号3", "MS4wLjABAAAAexample"),
    ("示例账号4", "MS4wLjABAAAAexample"),
    ("示例账号5", "MS4wLjABAAAAexample"),
]

MAX_PER_ACCOUNT = 40   # 每个账号最多采集条数
MIN_LIKES = 300        # 进入转写候选的最低点赞
MAX_TRANSCRIBE = 30    # 转写候选上限（按点赞取 top）


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

    prof_card = dict(card)
    prof_card["对标账号"] = [f"https://www.douyin.com/user/{uid}" for _, uid in EXT_ACCOUNTS]
    prof_card["关键词"] = []
    prof_card["采集设置"] = dict(card.get("采集设置") or {})
    prof_card["采集设置"]["每个来源最多视频数"] = MAX_PER_ACCOUNT
    prof_card["采集设置"]["滚动上限"] = 30
    log.info("采集 %d 个对标账号的更多作品（每号最多 %d 条）...",
             len(EXT_ACCOUNTS), MAX_PER_ACCOUNT)
    prof = asyncio.run(DouyinCollector(prof_card).run(out))

    # 高赞筛选 → 转写候选
    items = [v for v in prof.get("视频", []) if v.get("digg_count", 0) >= MIN_LIKES]
    items.sort(key=lambda v: -v.get("digg_count", 0))
    for v in items[:MAX_TRANSCRIBE]:
        v["recommend"] = True
    summary = {
        "客户": card.get("客户"),
        "来源": "语料扩充（对标账号更多作品）",
        "总数": len(prof.get("视频", [])),
        "推荐数": min(len(items), MAX_TRANSCRIBE),
        "视频": items[:MAX_TRANSCRIBE],
    }
    write_json(out, summary)
    log.info("采集 %d 条，≥%d 赞 %d 条，转写候选 top %d", len(summary["视频"]),
             MIN_LIKES, len(items), len(summary["视频"]))


if __name__ == "__main__":
    main()
