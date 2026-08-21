# -*- coding: utf-8 -*-
"""② 转写：下载视频音频 → ASR 逐字稿。视频转完即删（需求确认）。

引擎：
- 设置 VOLC_ASR_APPID / VOLC_ASR_ACCESS_TOKEN → 豆包语音识别大模型
- 否则 → 本地 faster-whisper（首次需下载模型，走 hf-mirror）
"""
import base64
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

from common import UA, load_card, read_json, run_dir, setup_log

log = logging.getLogger(__name__)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ASR_SUBMIT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
ASR_QUERY = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"


def download_video(url: str, out_mp4: Path):
    """带抖音 referer 下载视频文件。"""
    headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out_mp4, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    log.info("已下载 %s (%.1f MB)", out_mp4.name, out_mp4.stat().st_size / 1e6)


def extract_audio(mp4: Path, wav: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True, capture_output=True,
    )


def asr_doubao(wav: Path) -> str:
    appid = os.environ.get("VOLC_ASR_APPID")
    token = os.environ.get("VOLC_ASR_ACCESS_TOKEN")
    if not appid or not token:
        raise RuntimeError("缺少 VOLC_ASR_APPID / VOLC_ASR_ACCESS_TOKEN")
    b64 = base64.b64encode(wav.read_bytes()).decode()
    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": "volc.bigasr.auc",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
    }
    payload = {
        "app": {"appid": appid, "token": token, "cluster": "volc_auc_common"},
        "user": {"uid": "dy_pipeline"},
        "audio": {"format": "wav", "data": b64},
        "request": {
            "model_name": "bigmodel",
            "enable_punc": True,
            "enable_itn": True,
            "result_type": "full",
            "language": "zh-CN",
        },
    }
    r = requests.post(ASR_SUBMIT, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    resp = r.json()
    body = resp.get("resp") or resp
    if body.get("status_code") == 2000:
        return (body.get("text") or "").strip()
    task_id = resp.get("id")
    if not task_id:
        raise RuntimeError(f"豆包ASR提交失败: {json.dumps(resp, ensure_ascii=False)[:400]}")
    # 轮询结果
    for _ in range(60):
        time.sleep(2)
        q = requests.get(ASR_QUERY, params={"appid": appid, "id": task_id},
                         headers=headers, timeout=60)
        q.raise_for_status()
        qr = q.json().get("resp") or q.json()
        if qr.get("status_code") == 2000:
            return (qr.get("text") or "").strip()
        if qr.get("status_code") in (2001, 2002):  # 处理中
            continue
        raise RuntimeError(f"豆包ASR失败: {json.dumps(q.json(), ensure_ascii=False)[:400]}")
    raise RuntimeError("豆包ASR超时")


_whisper_model = None


def get_whisper():
    """单例加载 whisper 模型，避免每条视频重复加载 483MB 模型文件。"""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        local = Path(__file__).resolve().parent.parent / "data" / "models" / "faster-whisper-small"
        model_spec = str(local) if (local / "model.bin").exists() else "small"
        log.info("加载 whisper 模型: %s", model_spec)
        _whisper_model = WhisperModel(model_spec, device="cpu", compute_type="int8")
    return _whisper_model


def asr_whisper(wav: Path) -> str:
    model = get_whisper()
    segments, _ = model.transcribe(str(wav), language="zh", vad_filter=True)
    return "".join(seg.text for seg in segments).strip()


def transcribe_one(item: dict, out_dir: Path, engine: str) -> str:
    """下载→提取音频→转写→删视频，返回逐字稿文本。"""
    aid = item["aweme_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = out_dir / f"{aid}.txt"
    if txt.exists() and txt.read_text(encoding="utf-8").strip():
        return txt.read_text(encoding="utf-8").strip()

    play = item.get("play_url")
    if not play:
        log.warning("[%s] 无播放地址，跳过", aid)
        return ""
    mp4 = out_dir / f"{aid}.mp4"
    wav = out_dir / f"{aid}.wav"
    try:
        download_video(play, mp4)
        extract_audio(mp4, wav)
        text = asr_doubao(wav) if engine == "doubao" else asr_whisper(wav)
        if text:
            txt.write_text(text, encoding="utf-8")
        return text
    finally:
        for f in (mp4, wav):  # 需求确认：转完即删视频与音频
            if f.exists():
                f.unlink()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true", help="新建运行目录（不复用上次）")
    ap.add_argument("--run", default="", help="指定运行目录（用于独立语料目录）")
    ap.add_argument("--limit", type=int, default=0, help="只转写前 N 条（调试用）")
    args = ap.parse_args()

    card = load_card(args.card)
    if args.run:
        d = Path(args.run)
    else:
        d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    cand = read_json(d / "selected_candidates.json") or read_json(d / "candidates.json")
    if not cand:
        sys.exit("candidates.json 不存在，请先跑 collector/视频筛选")
    if read_json(d / "selected_candidates.json"):
        items = cand["视频"]                      # 人工筛选集：全部转写
    else:
        items = [v for v in cand["视频"] if v.get("recommend")]
    if args.limit:
        items = items[: args.limit]
    engine = card.get("转写设置", {}).get("引擎", "auto")
    if engine == "auto":
        engine = "doubao" if os.environ.get("VOLC_ASR_APPID") else "whisper"
    log.info("转写引擎: %s，共 %d 条", engine, len(items))

    out_dir = d / "transcripts"
    for i, item in enumerate(items, 1):
        try:
            text = transcribe_one(item, out_dir, engine)
            log.info("[%d/%d] %s -> %d 字", i, len(items), item["aweme_id"], len(text))
        except Exception as e:
            log.error("[%d/%d] %s 转写失败: %s", i, len(items), item["aweme_id"], e)


if __name__ == "__main__":
    main()
