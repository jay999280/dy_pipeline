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

from common import UA, load_card, read_json, run_dir, setup_log, write_json

log = logging.getLogger(__name__)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ASR_SUBMIT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
ASR_QUERY = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"


def download_video(url: str, out_mp4: Path, retries: int = 2):
    """带抖音 referer 下载视频文件，失败重试（URL 过期/网络抖动）。"""
    headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    last_err = None
    for attempt in range(retries):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(out_mp4, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
            log.info("已下载 %s (%.1f MB)", out_mp4.name, out_mp4.stat().st_size / 1e6)
            return
        except Exception as e:
            last_err = e
            log.warning("下载失败(第%d次): %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"视频下载失败（播放地址可能过期，需重新采集刷新）: {last_err}")


def extract_audio(mp4: Path, wav: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True, capture_output=True,
    )


def extract_frames(mp4: Path, frames_dir: Path, interval: float) -> list:
    """ffmpeg 按 interval 秒抽帧（视觉拆解用），返回帧文件路径列表。"""
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / "frame_%04d.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4), "-vf", f"fps=1/{interval}", "-q:v", "3", str(pattern)],
        check=True, capture_output=True,
    )
    return sorted(frames_dir.glob("frame_*.jpg"))


def _doubao_segments(body: dict) -> list:
    """从豆包 ASR 响应提取句级时间戳（毫秒→秒）。字段缺失时返回空列表（降级为无时间戳）。"""
    segs = []
    for u in body.get("utterances") or []:
        t = u.get("text")
        if not t:
            continue
        s = u.get("start_time", u.get("start"))
        e = u.get("end_time", u.get("end"))
        segs.append({
            "start": round((float(s) if s is not None else 0) / 1000, 2),
            "end": round((float(e) if e is not None else 0) / 1000, 2),
            "text": str(t),
        })
    return segs


def asr_doubao(wav: Path):
    """豆包语音识别大模型 → (全文, 句级时间戳列表)。"""
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
            "enable_utt": True,      # 开启句级时间戳（utterances）
            "result_type": "full",
            "language": "zh-CN",
        },
    }
    r = requests.post(ASR_SUBMIT, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    resp = r.json()
    body = resp.get("resp") or resp
    if body.get("status_code") == 2000:
        return (body.get("text") or "").strip(), _doubao_segments(body)
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
            return (qr.get("text") or "").strip(), _doubao_segments(qr)
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


def asr_whisper(wav: Path):
    """本地 faster-whisper → (全文, 句级时间戳列表)。segments 自带 start/end。"""
    model = get_whisper()
    segments, _ = model.transcribe(str(wav), language="zh", vad_filter=True)
    segs = []
    text = ""
    for seg in segments:
        text += seg.text
        segs.append({
            "start": round(float(seg.start), 2),
            "end": round(float(seg.end), 2),
            "text": seg.text.strip(),
        })
    return text.strip(), segs


def transcribe_one(item: dict, out_dir: Path, engine: str, interval: float = 2.5) -> dict:
    """下载→提取音频→转写→抽帧→删视频，返回 {"text": str, "segments": [...]}。
    同时写 transcripts/<id>.txt（纯文本，兼容旧读取）与 transcripts/<id>.json（带时间戳）。
    抽帧产物存 vision/<id>/（供视觉拆解层消费），视频转完即删。"""
    aid = item["aweme_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = out_dir / f"{aid}.txt"
    jso = out_dir / f"{aid}.json"
    if txt.exists() and txt.read_text(encoding="utf-8").strip():
        text = txt.read_text(encoding="utf-8").strip()
        if jso.exists():
            data = read_json(jso) or {}
            return {"text": text, "segments": data.get("segments", [])}
        return {"text": text, "segments": []}  # 旧数据无时间戳

    play = item.get("play_url")
    if not play:
        log.warning("[%s] 无播放地址，跳过", aid)
        return {"text": "", "segments": []}
    mp4 = out_dir / f"{aid}.mp4"
    wav = out_dir / f"{aid}.wav"
    try:
        download_video(play, mp4)
        extract_audio(mp4, wav)
        text, segs = asr_doubao(wav) if engine == "doubao" else asr_whisper(wav)
        if text:
            txt.write_text(text, encoding="utf-8")
            write_json(jso, {"text": text, "segments": segs})
        # 抽帧（视觉拆解用）：帧图保留，视频随后删除
        frames_dir = out_dir.parent / "vision" / aid
        if not frames_dir.exists() or not any(frames_dir.glob("frame_*.jpg")):
            try:
                extract_frames(mp4, frames_dir, interval)
            except Exception as e:
                log.warning("[%s] 抽帧失败（跳过视觉）: %s", aid, e)
        return {"text": text, "segments": segs}
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
    interval = float(card.get("视觉设置", {}).get("抽帧间隔秒", 2.5))
    for i, item in enumerate(items, 1):
        try:
            res = transcribe_one(item, out_dir, engine, interval)
            n_seg = len(res.get("segments", []))
            log.info("[%d/%d] %s -> %d 字（%d 段时间戳）",
                     i, len(items), item["aweme_id"], len(res.get("text", "")), n_seg)
        except Exception as e:
            log.error("[%d/%d] %s 转写失败: %s", i, len(items), item["aweme_id"], e)


if __name__ == "__main__":
    main()
