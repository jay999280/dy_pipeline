# -*- coding: utf-8 -*-
"""视觉拆解层：GLM 视觉模型看帧 → 真实分镜表。

分两步（解耦，视频只下载一次）：
1. transcribe 阶段下载视频后调用 transcribe.extract_frames() 抽帧（本地 ffmpeg），
   帧图留 data/<run>/vision/<vid>/frame_*.jpg
2. 本模块 analyze_frames() 读帧图，分批喂 GLM 视觉模型（glm-4v-flash 免费默认，
   需求卡 视觉设置.模型 可换 glm-4.5v），产出 vision/<vid>.json：
   [{"秒": float, "景别": str, "画面内容": str, "画面文字": str}]

用法: python src/vision.py config/<客户>_需求卡.yaml [--limit N]
"""
import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

from common import load_card, read_json, run_dir, setup_log, write_json
from transcribe import download_video, extract_frames

log = logging.getLogger(__name__)

DEFAULT_MODEL = "glm-4v-flash"   # 免费档默认；可配 glm-4.5v
DEFAULT_INTERVAL = 2.5
BATCH = 6                        # 每批喂给视觉模型的帧数


def _model(card: dict) -> str:
    return str(card.get("视觉设置", {}).get("模型", DEFAULT_MODEL)).strip() or DEFAULT_MODEL


def _interval(card: dict) -> float:
    return float(card.get("视觉设置", {}).get("抽帧间隔秒", DEFAULT_INTERVAL))


def _extract_json_array(text: str) -> list:
    try:
        d = json.loads(text)
        if isinstance(d, list):
            return d
    except Exception:
        pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if isinstance(d, list):
                return d
        except Exception:
            pass
    raise ValueError("无法解析视觉模型返回: " + text[:200])


def _call_vision(model: str, api_key: str, content: list) -> str:
    base = os.environ.get("LLM_API_BASE", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    url = f"{base}/chat/completions"
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "temperature": 0.2}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(5):
        try:
            r = requests.post(url, json=body, headers=headers, timeout=180)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning("视觉模型调用失败(第%d次): %s", attempt + 1, e)
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    return ""


def _describe_batch(frames: list, start_idx: int, interval: float,
                    model: str, api_key: str) -> list:
    """把一批帧图喂给视觉模型，返回该批帧的分镜描述列表。"""
    content = [{"type": "text", "text": (
        "你是视频分镜拆解专家。下面是一段竖屏短视频按时间抽出的若干帧，"
        "每帧图片前都标注了它的秒数。请逐帧识别，只输出一个 JSON 数组：\n"
        '[{"秒": 数字, "景别": "远景|全景|中景|近景|特写", '
        '"画面内容": "画面拍的是什么（人物/动作/物品/场景），25字内", '
        '"画面文字": "画面上的字幕/花字/贴纸文字，逐字识别含标点，没有写\\"无\\""}]\n'
        "景别按人物在画面中的占比判断；画面文字必须逐字识别，不要概括。"
    )}]
    for j, fp in enumerate(frames):
        b64 = base64.b64encode(fp.read_bytes()).decode()
        content.append({"type": "text", "text": f"[第{round((start_idx + j) * interval, 1)}秒]"})
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    raw = _call_vision(model, api_key, content)
    return _extract_json_array(raw)


def analyze_frames(video: dict, run_dir: Path, card: dict, api_key: str) -> list:
    """读视频帧图 → GLM 看帧 → 写 vision/<vid>.json，返回分镜表。断点续跑。"""
    vid = video["aweme_id"]
    out_json = run_dir / "vision" / f"{vid}.json"
    if out_json.exists():
        data = read_json(out_json)
        if data:
            return data

    frames_dir = run_dir / "vision" / vid
    interval = _interval(card)
    frames = sorted(frames_dir.glob("frame_*.jpg")) if frames_dir.exists() else []
    if not frames:
        # 帧图缺失（旧数据/独立跑）：下载补抽
        play = video.get("play_url")
        if not play:
            log.warning("[%s] 无播放地址，跳过视觉拆解", vid)
            return []
        mp4 = run_dir / f"{vid}_tmp.mp4"
        try:
            download_video(play, mp4)
            frames = extract_frames(mp4, frames_dir, interval)
        finally:
            if mp4.exists():
                mp4.unlink()
    if not frames:
        log.warning("[%s] 抽帧为空，跳过视觉拆解", vid)
        return []

    model = _model(card)
    shots = []
    for i in range(0, len(frames), BATCH):
        batch = frames[i:i + BATCH]
        try:
            arr = _describe_batch(batch, i, interval, model, api_key)
            shots.extend(arr)
        except Exception as e:
            log.error("[%s] 第 %d 批看帧失败: %s", vid, i // BATCH + 1, e)
        log.info("[%s] 视觉拆解 %d/%d 帧", vid, min(i + BATCH, len(frames)), len(frames))

    clean = []
    for s in shots:
        if not isinstance(s, dict):
            continue
        clean.append({
            "秒": s.get("秒"),
            "景别": str(s.get("景别", "")).strip(),
            "画面内容": str(s.get("画面内容", "")).strip(),
            "画面文字": str(s.get("画面文字", "无")).strip() or "无",
        })
    write_json(out_json, clean)
    return clean


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true", help="新建运行目录（不复用上次）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试用）")
    args = ap.parse_args()

    card = load_card(args.card)
    d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        sys.exit("缺少 LLM_API_KEY / DEEPSEEK_API_KEY 环境变量")

    cand = read_json(d / "selected_candidates.json") or read_json(d / "candidates.json")
    if not cand:
        sys.exit("candidates.json 不存在，请先跑采集")
    if read_json(d / "selected_candidates.json"):
        items = cand["视频"]
    else:
        items = [v for v in cand["视频"] if v.get("recommend")]
    if args.limit:
        items = items[: args.limit]

    log.info("视觉拆解：%d 条视频，模型 %s，间隔 %.1fs", len(items), _model(card), _interval(card))
    done = 0
    import random as _random
    for v in items:
        try:
            shots = analyze_frames(v, d, card, api_key)
            if shots:
                done += 1
                log.info("视觉拆解完成 %d/%d: %s（%d 个分镜）",
                         done, len(items), v["aweme_id"], len(shots))
        except Exception as e:
            log.error("视觉拆解失败 %s: %s", v["aweme_id"], e)
        # 下载/采集间隔，缓解抖音批量下载风控
        time.sleep(_random.uniform(2.0, 5.0))


if __name__ == "__main__":
    main()
