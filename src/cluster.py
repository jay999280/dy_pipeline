# -*- coding: utf-8 -*-
"""④ 聚类：把逐条分析结果归纳为 N 个内容赛道。"""
import json
import logging
import os
import sys

from common import load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

from analyze import call_deepseek, get_api_key


def _overlap(a: str, b: str) -> int:
    return len(set(a) & set(b))


def assign_reps(tracks: list, rows: list, cand: dict) -> list:
    """确定性分配代表视频：不再信任 LLM 返回的 ID。

    每个赛道按「视频标题+赛道倾向 与 赛道名+定位 的字符重合度」打分，
    重合度优先、点赞次之，跨赛道去重；无重合时按点赞兜底。
    逐字稿不足 100 字的（无口播/纯音乐）不选为代表视频（无法作为改编范本）。
    """
    min_chars = 100
    used = set()
    for t in tracks:
        name = str(t.get("名称", "")) + str(t.get("定位", ""))
        scored = []
        for r in rows:
            vid = r.get("video_id")
            if vid in used or r.get("字数", 0) < min_chars:
                continue
            text = str(r.get("标题", "")) + str(r.get("赛道倾向", ""))
            scored.append((_overlap(name, text), -cand.get(vid, {}).get("digg_count", 0), vid))
        scored.sort(reverse=True)  # 重合度降序、点赞降序
        rep = [vid for s, _, vid in scored if s > 0][:3]
        if not rep:
            rep = [vid for _, _, vid in scored[:2]]
        for vid in rep:
            used.add(vid)
        t["代表视频"] = rep
    return tracks


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true", help="新建运行目录（不复用上次）")
    args = ap.parse_args()

    api_key = get_api_key()
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    card = load_card(args.card)
    d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    analysis = read_json(d / "analysis.json")
    cand = read_json(d / "selected_candidates.json") or read_json(d / "candidates.json")
    if not analysis or not cand:
        sys.exit("analysis.json / candidates.json 不存在")

    n_tracks = int(card.get("生成设置", {}).get("赛道数", 3))
    by_id = {v["aweme_id"]: v for v in cand["视频"]}

    # 组装每条的紧凑摘要，控制 token
    rows = []
    for a in analysis.get("视频分析", []):
        vid = a.get("video_id")
        v = by_id.get(vid, {})
        if v.get("对照"):
            continue  # 对照组不进赛道聚类
        tf = d / "transcripts" / f"{vid}.txt"
        n_chars = len(tf.read_text(encoding="utf-8").strip()) if tf.exists() else 0
        rows.append({
            "video_id": vid,
            "标题": v.get("desc", "")[:60],
            "点赞": v.get("digg_count", 0),
            "赛道倾向": a.get("赛道倾向", ""),
            "结构": [s.get("功能", "") for s in (a.get("叙事结构与节奏") or {}).get("段落表", [])][:6],
            "模板": (a.get("可复用模板") or "")[:120],
            "字数": n_chars,
        })

    prompt = f"""你是短视频内容策划。以下是 {len(rows)} 条爆款视频的结构化摘要（JSON）。

【客户业务】{card.get('业务简介', '').strip()}
【客户卖点】{'、'.join(card.get('卖点') or [])}
【排除规则】{card.get('排除规则', '')}

请把它们归纳为恰好 {n_tracks} 个内容赛道，只输出一个 JSON 对象。
赛道必须紧密围绕客户业务与卖点（见上文【客户业务】【客户卖点】，不得归纳出与客户业务无关的泛生活方式赛道）：
{{
  "赛道": [
    {{
      "名称": "赛道名（10字内）",
      "定位": "这个赛道讲什么、服务什么人群，1-2句",
      "典型开头": "这类视频最常见的3秒钩子写法",
      "常见结构": "步骤化结构，如：痛点→反常识结论→3个判断标准→CTA",
      "可拍场景": "适配客户可拍的画面场景",
      "代表视频": ["video_id1", "video_id2"],
      "内容角度": ["角度1", "角度2", "角度3", "角度4", "角度5"],
      "选题清单": ["具体选题1", "具体选题2", "...共15个"]
    }}
  ]
}}
- 代表视频从输入里选 2~3 个真实 video_id。
- 内容角度：给该赛道列出 5 个互不重复的脚本切入点（例如：材料对比/价格真相/安装工艺/售后避坑/案例展示），让同赛道每条脚本讲不同侧面。
- 选题清单：把该赛道的话题与角度交叉展开成 15 个具体可拍选题（每条一个明确的脚本切入点，如"台下盆发霉改造翻车""全铝vs不锈钢价格差多少"），供多轮脚本生成按序取用、避免重复。"""

    log.info("聚类 %d 条摘要 → %d 个赛道", len(rows), n_tracks)
    result = call_deepseek([{"role": "user", "content": prompt}], api_key, temperature=0.4)

    # 后处理：确定性分配真实代表视频（不信任 LLM 返回的 ID）
    assign_reps(result.get("赛道", []), rows, by_id)
    write_json(d / "tracks.json", result)
    # 选题库沉淀：跨 run 复用，供 generate 按序取用、避开已用
    topics = {t.get("名称", ""): t.get("选题清单", []) for t in result.get("赛道", [])}
    write_json(d / "topics.json", topics)
    for t in result.get("赛道", []):
        log.info("赛道: %s（代表视频 %s，选题 %d 个）",
                 t.get("名称"), t.get("代表视频"), len(t.get("选题清单") or []))


if __name__ == "__main__":
    main()
