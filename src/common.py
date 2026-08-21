# -*- coding: utf-8 -*-
"""公共工具：路径、日志、JSON 读写。"""
from pathlib import Path
import json
import logging
import sys
from datetime import datetime

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"

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
    for key in ("客户", "业务简介", "生成设置"):
        if key not in card:
            sys.exit(f"需求卡缺少必填字段: {key}")
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
