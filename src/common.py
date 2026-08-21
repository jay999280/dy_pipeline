# -*- coding: utf-8 -*-
"""公共工具：路径、日志、JSON 读写。"""
from pathlib import Path
import json
import logging
import os
import sys
from datetime import datetime

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"

# 加载项目根目录 .env（密钥配置）；未安装 python-dotenv 时静默跳过
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def load_card(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        sys.exit(f"需求卡不存在: {p}")
    with open(p, encoding="utf-8") as f:
        card = yaml.safe_load(f)
    errors = []
    # 必填字段
    for key in ("客户", "业务简介", "生成设置"):
        if key not in card or not card.get(key):
            errors.append(f"缺少必填字段: {key}")
    # 生成设置
    gs = card.get("生成设置") or {}
    for k in ("赛道数", "每赛道脚本数"):
        if k not in gs:
            errors.append(f"生成设置缺少: {k}")
        elif not isinstance(gs[k], int):
            errors.append(f"生成设置.{k} 必须是整数，当前为 {gs[k]!r}")
    if gs.get("主攻赛道") and not isinstance(gs.get("主攻赛道"), str):
        errors.append("生成设置.主攻赛道 必须是字符串（赛道名或留空）")
    # 转写引擎枚举
    eng = (card.get("转写设置") or {}).get("引擎", "auto")
    if eng not in ("auto", "doubao", "whisper"):
        errors.append(f"转写设置.引擎 取值非法: {eng!r}（应为 auto/doubao/whisper）")
    # 视觉模型/抽帧间隔
    vis = card.get("视觉设置") or {}
    if vis.get("抽帧间隔秒") is not None:
        try:
            if float(vis["抽帧间隔秒"]) <= 0:
                errors.append("视觉设置.抽帧间隔秒 必须 > 0")
        except (TypeError, ValueError):
            errors.append(f"视觉设置.抽帧间隔秒 非法: {vis['抽帧间隔秒']!r}")
    # 语料扩充账号结构
    for i, a in enumerate(card.get("语料扩充账号") or []):
        if isinstance(a, dict) and not a.get("sec_uid"):
            errors.append(f"语料扩充账号第 {i+1} 项缺少 sec_uid")
        elif not isinstance(a, (dict, str)):
            errors.append(f"语料扩充账号第 {i+1} 项格式非法（应为 昵称+sec_uid 对象或字符串）")
    if errors:
        sys.exit("需求卡校验失败（" + str(p) + "）：\n  - " + "\n  - ".join(errors))
    return card


def run_dir(card: dict, resume: bool = False) -> Path:
    """返回本次运行的产物目录（data/<客户>/<run>）。"""
    cust = str(card["客户"]).strip().replace("/", "_").replace("\\", "_")
    base = DATA / cust
    base.mkdir(parents=True, exist_ok=True)

    checkpoint = base / "last_run.txt"
    if resume and checkpoint.exists():
        name = checkpoint.read_text(encoding="utf-8").strip("\ufeff").strip()
        d = base / name
        if d.exists():
            return d

    d = base / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    d.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(d.name, encoding="utf-8")
    return d


def setup_log(log_file: Path):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    try:  # Windows GBK 控制台遇到 emoji 会崩，替换而不是报错
        sh.stream.reconfigure(errors="replace")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def stage_done(path: Path) -> bool:
    return path.exists()
