# -*- coding: utf-8 -*-
"""评论采集：对人工确认入选的视频采集评论区，落 comments/<vid>.json。

评论是受众真实痛点、争议点、行话的一手来源，供拆解阶段注入（"评论区武器"字段）。
用法: python src/comments.py config/<客户>_需求卡.yaml [--limit N]
"""
import asyncio
import logging
import sys

from collector import collect_comments
from common import load_card, read_json, run_dir, setup_log

log = logging.getLogger(__name__)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true", help="新建运行目录（不复用上次）")
    ap.add_argument("--limit", type=int, default=0, help="只采集前 N 条（调试用）")
    args = ap.parse_args()

    card = load_card(args.card)
    d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    cand = read_json(d / "selected_candidates.json") or read_json(d / "candidates.json")
    if not cand:
        sys.exit("candidates.json 不存在，请先跑采集")
    if read_json(d / "selected_candidates.json"):
        items = cand["视频"]
    else:
        items = [v for v in cand["视频"] if v.get("recommend")]
    if args.limit:
        items = items[: args.limit]

    ids = [v["aweme_id"] for v in items if v.get("aweme_id")]
    log.info("评论采集：%d 条视频", len(ids))
    asyncio.run(collect_comments(ids, d / "comments", max_per=30))


if __name__ == "__main__":
    main()
