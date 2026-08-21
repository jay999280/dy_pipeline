# -*- coding: utf-8 -*-
"""③ 分析：LLM 结构化拆解每条爆款视频。

LLM 端点通过环境变量配置（默认 DeepSeek 官方 Chat Completions）：
  LLM_API_BASE     基础地址，如 https://api.deepseek.com 或 http://127.0.0.1:57321/v1
  LLM_API_PROTOCOL responses | chat（默认：本地地址用 responses，否则 chat）
  LLM_MODEL        模型名，默认 deepseek-chat
  LLM_API_KEY      API Key（也可用 DEEPSEEK_API_KEY）
"""
import concurrent.futures as cf
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

from common import DATA, load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

API_BASE = os.environ.get("LLM_API_BASE", "https://api.deepseek.com").rstrip("/")
PROTOCOL = os.environ.get(
    "LLM_API_PROTOCOL", "responses" if "127.0.0.1" in API_BASE or "localhost" in API_BASE else "chat")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")


def get_api_key():
    return os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")


# ---------- LLM 调用缓存（同 prompt+model+temp 命中则零计费） ----------
def _cache_key(messages: list, model: str, temperature: float) -> str:
    raw = json.dumps({"messages": messages, "model": model, "temperature": temperature},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str):
    p = DATA / ".llm_cache" / key[:2] / (key + ".json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _cache_put(key: str, result: dict):
    p = DATA / ".llm_cache" / key[:2] / (key + ".json")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


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
    key = _cache_key(messages, MODEL, temperature)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    result = _call_llm_impl(messages, api_key, temperature)
    if result:
        _cache_put(key, result)
    return result


def _call_llm_impl(messages: list, api_key: str, temperature: float = 0.3) -> dict:
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
  "钩子设计": {
    "前3秒原话": "逐字引用开头 3 秒说了什么",
    "类型": "反常识/痛点/悬念/冲突/信息差/利益承诺/共鸣",
    "抓人机制": "为什么有效：冲突对立/悬念缺口/利益直接/身份代入（一句说明）",
    "强度": "1到10"
  },
  "叙事结构与节奏": {
    "段落表": [{"段": 1, "起止秒": "0-3", "功能": "钩子/痛点放大/给方案/对比/CTA", "信息密度": "高|中|低", "转折点": "是|否", "要点": "概括而非抄原文"}],
    "节奏曲线": "渐强/先扬后抑/高潮中置（一句描述）",
    "总时长秒": 数字
  },
  "情绪共鸣点": [{"类型": "痛点|爽点|恐惧|好奇|认同|省钱", "触发秒": 数字, "触发语句": "原话", "共鸣逻辑": "触达了什么心理"}],
  "结尾互动引导": {"形式": "评论|点赞|关注|私信|收藏", "话术": "原话", "设计逻辑": "为什么这个引导有效"},
  "爆点归因": "这条为什么爆：情绪冲突、信息密度还是争议点，一句话",
  "评论区武器": "从评论数据推断的受众心理与高频痛点词；没有评论数据就写'未知'",
  "可复用模板": "去掉具体业务内容后的句式/结构骨架",
  "适配本客户": "改成客户业务后最自然的切入角度，2-3句"
}
硬性要求：段落表起止秒累计覆盖总时长的 90% 以上；情绪共鸣点必须带触发秒。"""


def build_prompt(video: dict, transcript: str, card: dict, track_names: list) -> str:
    return f"""你是短视频爆款拆解专家。下面是一条抖音爆款视频的数据，请按字段拆解。

【客户业务】{card.get('业务简介', '').strip()}
【客户卖点】{'、'.join(card.get('卖点') or [])}
【客户人设】{card.get('人设', '')}
【目标客户】{card.get('目标客户', '')}
【可选赛道】{'、'.join(track_names) if track_names else '由你归纳'}

【视频标题】{video.get('desc', '')}
【账号】{video.get('author', '')}
【点赞】{video.get('digg_count', 0)} 【评论】{video.get('comment_count', 0)} 【转发】{video.get('share_count', 0)}
【时长秒】{round((video.get('duration_ms') or 0) / 1000)}

【口播逐字稿 + 时间轴 + 画面分镜】
{transcript[:8000] or '（无逐字稿，仅凭标题和数据分析）'}

{SCHEMA_HINT}"""


def assemble_context(d: Path, tdir: Path, v: dict) -> str:
    """组装拆解上下文：画面分镜表(前置，短) + 评论 + 逐字稿全文 + 时间轴。"""
    vid = v["aweme_id"]
    parts = []
    vis = d / "vision" / f"{vid}.json"
    if vis.exists():
        shots = read_json(vis)
        if shots:
            parts.append("【画面分镜表】\n" + json.dumps(shots, ensure_ascii=False))
    cmt = d / "comments" / f"{vid}.json"
    if cmt.exists():
        comments = read_json(cmt)
        if comments:
            top = sorted(comments, key=lambda c: -c.get("赞", 0))[:20]
            parts.append("【评论区 TOP20】\n" + json.dumps(top, ensure_ascii=False))
    tf = tdir / f"{vid}.txt"
    if tf.exists():
        parts.append("【逐字稿全文】\n" + tf.read_text(encoding="utf-8").strip())
    ts = tdir / f"{vid}.json"
    if ts.exists():
        segs = (read_json(ts) or {}).get("segments", [])
        if segs:
            parts.append("【逐字稿时间轴】\n" + "".join(
                f"[{s['start']:.0f}s-{s['end']:.0f}s]{s['text']}" for s in segs))
    return "\n\n".join(parts)


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
            txt = assemble_context(d, tdir, v)
            futs.append(ex.submit(analyze_one, v, txt, card, track_names, api_key))
        for i, fut in enumerate(cf.as_completed(futs), 1):
            results.append(fut.result())
            log.info("分析完成 %d/%d", i, len(futs))

    def _hook_score(a):
        try:
            return -float((a.get("钩子设计") or {}).get("强度") or 0)
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
