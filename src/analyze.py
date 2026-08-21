# -*- coding: utf-8 -*-
"""③ 分析：LLM 结构化拆解每条爆款视频。

LLM 端点通过环境变量配置（默认 DeepSeek 官方 Chat Completions）：
  LLM_API_BASE     基础地址，如 https://api.deepseek.com 或 http://127.0.0.1:57321/v1
  LLM_API_PROTOCOL responses | chat（默认：本地地址用 responses，否则 chat）
  LLM_MODEL        模型名，默认 deepseek-chat
  LLM_API_KEY      API Key（也可用 DEEPSEEK_API_KEY）
"""
import concurrent.futures as cf
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

from common import load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

API_BASE = os.environ.get("LLM_API_BASE", "https://api.deepseek.com").rstrip("/")
PROTOCOL = os.environ.get(
    "LLM_API_PROTOCOL", "responses" if "127.0.0.1" in API_BASE or "localhost" in API_BASE else "chat")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")


def get_api_key():
    return os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")


def _extract_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError("无法解析 LLM 返回的 JSON: " + text[:200])


def call_llm(messages: list, api_key: str, temperature: float = 0.3) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if PROTOCOL == "responses":
        url = f"{API_BASE}/responses"
        body = {
            "model": MODEL,
            "input": "\n\n".join(m.get("content", "") for m in messages),
            "temperature": temperature,
            "text": {"format": {"type": "json_object"}},
        }
        for attempt in range(5):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=300)
                r.raise_for_status()
                resp = r.json()
                if resp.get("status") == "failed":
                    raise RuntimeError(resp.get("message", "unknown"))
                texts = []
                for item in resp.get("output") or []:
                    if item.get("type") == "message":
                        for c in item.get("content") or []:
                            if c.get("type") == "output_text":
                                texts.append(c.get("text") or "")
                return _extract_json("".join(texts))
            except Exception as e:
                log.warning("LLM 调用失败(第%d次): %s", attempt + 1, e)
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
    else:
        url = f"{API_BASE}/chat/completions"
        body = {
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        for attempt in range(5):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=120)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                return _extract_json(content)
            except Exception as e:
                log.warning("LLM 调用失败(第%d次): %s", attempt + 1, e)
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
    return {}


def call_deepseek(messages: list, api_key: str, temperature: float = 0.3) -> dict:
    """兼容旧名字，cluster/generate 继续用。"""
    return call_llm(messages, api_key, temperature)

SCHEMA_HINT = """只输出一个 JSON 对象，不要输出任何其他文字，字段如下：
{
  "赛道倾向": "从给定候选赛道里选最接近的一个名称，或写'其他'",
  "hook": {"前3秒说什么": "...", "类型": "反常识/痛点/悬念/冲突/信息差", "钩子强度": 1到5},
  "结构拆解": [{"段": 1, "功能": "痛点放大/给方案/对比/CTA等", "原文要点": "概括而非抄原文"}],
  "爆点归因": "这条为什么爆：情绪冲突、信息密度还是争议点，一句话",
  "评论区武器": "从评论数和高赞倾向推断的受众心理（没有评论数据就写'未知'）",
  "可复用模板": "去掉具体业务内容后的句式/结构骨架",
  "适配本客户": "改成客户业务后最自然的切入角度，2-3句"
}"""


def build_prompt(video: dict, transcript: str, card: dict, track_names: list) -> str:
    return f"""你是短视频爆款拆解专家。下面是一条抖音爆款视频的数据，请按字段拆解。

【客户业务】{card.get('业务简介', '').strip()}
【客户卖点】{'、'.join(card.get('卖点') or [])}
【客户人设】{card.get('人设', '')}
【可选赛道】{'、'.join(track_names) if track_names else '由你归纳'}

【视频标题】{video.get('desc', '')}
【账号】{video.get('author', '')}
【点赞】{video.get('digg_count', 0)} 【评论】{video.get('comment_count', 0)} 【转发】{video.get('share_count', 0)}
【时长秒】{round((video.get('duration_ms') or 0) / 1000)}

【口播逐字稿】
{transcript[:4000] or '（无逐字稿，仅凭标题和数据分析）'}

{SCHEMA_HINT}"""


def analyze_one(video: dict, transcript: str, card: dict, track_names: list, api_key: str) -> dict:
    try:
        result = call_deepseek(
            [{"role": "user", "content": build_prompt(video, transcript, card, track_names)}],
            api_key,
        )
        result["video_id"] = video["aweme_id"]
        return result
    except Exception as e:
        log.error("[%s] 分析失败: %s", video.get("aweme_id"), e)
        return {"video_id": video.get("aweme_id"), "error": str(e)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true", help="新建运行目录（不复用上次）")
    ap.add_argument("--run", default="", help="指定运行目录（用于独立语料目录）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    api_key = get_api_key()
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    card = load_card(args.card)
    if args.run:
        d = Path(args.run)
    else:
        d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    cand = read_json(d / "selected_candidates.json") or read_json(d / "candidates.json")
    if not cand:
        sys.exit("candidates.json 不存在，请先跑 collector/视频筛选")
    items = [v for v in cand["视频"] if v.get("recommend")]

    # 断点续跑：跳过已成功分析的视频，只补失败的；有人工筛选时丢弃筛选集外的旧结果
    old = read_json(d / "analysis.json") or {}
    old_items = old.get("视频分析", [])
    if read_json(d / "selected_candidates.json"):
        valid_ids = {v["aweme_id"] for v in cand["视频"]}
        old_items = [a for a in old_items if a.get("video_id") in valid_ids]
    done_ids = {a.get("video_id") for a in old_items if "error" not in a}
    todo = [v for v in items if v["aweme_id"] not in done_ids]
    if args.limit:
        todo = todo[: args.limit]
    log.info("分析：%d 条已成功跳过，待分析 %d 条", len(done_ids), len(todo))
    items = todo

    # 先粗分组赛道名（用标题+账号让 LLM 归纳，或直接用上次聚类结果）
    old_tracks = read_json(d / "tracks.json")
    track_names = [t["名称"] for t in (old_tracks or {}).get("赛道", [])]

    tdir = d / "transcripts"
    log.info("分析 %d 条视频", len(items))
    results = []
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = []
        for v in items:
            txt = ""
            tf = tdir / f"{v['aweme_id']}.txt"
            if tf.exists():
                txt = tf.read_text(encoding="utf-8")
            futs.append(ex.submit(analyze_one, v, txt, card, track_names, api_key))
        for i, fut in enumerate(cf.as_completed(futs), 1):
            results.append(fut.result())
            log.info("分析完成 %d/%d", i, len(futs))

    def _hook_score(a):
        try:
            return -float((a.get("hook") or {}).get("钩子强度") or 0)
        except (TypeError, ValueError):
            return 0
    # 合并旧的（已成功的）+ 新的，按 video_id 去重（新的覆盖旧的）
    merged = {a.get("video_id"): a for a in old_items}
    for a in results:
        merged[a.get("video_id")] = a
    all_items = [a for a in merged.values() if "error" not in a]
    all_items.sort(key=_hook_score)
    write_json(d / "analysis.json", {"视频分析": all_items})


if __name__ == "__main__":
    main()
