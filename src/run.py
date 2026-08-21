# -*- coding: utf-8 -*-
"""总入口：需求卡驱动全流程，含两轮人工筛选门禁。

流程:
  ① account_screen 账号粗筛（AI 打分）→【第一轮人工选账号】
  ② video_screen   视频粗筛（AI 打分）→【第二轮人工选视频】
  ③ transcribe → analyze → cluster → generate（仅对已确认视频）

用法:
  python src/run.py config/<客户>_需求卡.yaml
  python src/run.py config/<客户>_需求卡.yaml --only analyze --force
  python src/run.py config/<客户>_需求卡.yaml --resume
人工确认: 每轮筛选产出候选清单 md 后退出(码2)，把选中的
账号/video_id 填入对应的 *_selected.json 再重跑即可继续。
"""
import subprocess
import sys
from pathlib import Path

from common import load_card, read_json, run_dir, stage_done, setup_log

SRC = Path(__file__).resolve().parent

STAGES = ["account_screen", "video_screen", "transcribe", "vision", "comments", "analyze", "cluster", "distill", "generate"]
# 不进默认链、但可通过 --only 单独跑的阶段（周期性/可选任务）
OPTIONAL = ["feedback", "collect_more"]


def stage_output(d: Path, stage: str) -> Path:
    return {
        "account_screen": d / "accounts_selected.json",   # 已确认账号列表
        "video_screen": d / "videos_selected.json",        # 已确认视频列表
        "transcribe": d / "transcripts",                   # 目录，非空即视为完成
        "vision": d / "vision",                            # 目录，有 json 即视为完成
        "comments": d / "comments",                        # 目录，有 json 即视为完成
        "analyze": d / "analysis.json",
        "cluster": d / "tracks.json",
        "distill": d.parent / "distill" / "模式库.json",   # 客户级知识资产，跨 run 复用
        "generate": d / "脚本池.xlsx",
        "feedback": d / "赛道复盘报告.md",
    }[stage]


def is_done(d: Path, stage: str) -> bool:
    if stage == "feedback":
        return False  # 周期性任务，有新数据就重跑
    out = stage_output(d, stage)
    if stage in ("vision", "comments"):
        return out.exists() and any(out.glob("*.json"))
    if stage in ("account_screen", "video_screen"):
        data = read_json(out) or []
        return len(data) > 0          # 人工确认文件已填写才算完成
    sel = read_json(d / "selected_candidates.json")
    if stage == "transcribe":
        if not sel:
            return out.exists() and any(out.iterdir())
        need = {v["aweme_id"] for v in sel["视频"]}
        have = {p.stem for p in out.glob("*.txt")} if out.exists() else set()
        return need <= have          # 已选视频全部转写完才算完成
    if stage == "analyze" and sel:
        need = {v["aweme_id"] for v in sel["视频"]}
        done = {a.get("video_id") for a in (read_json(d / "analysis.json") or {}).get("视频分析", [])
                if "error" not in a}
        return need <= done
    if stage in ("cluster", "generate") and (d / "selected_candidates.json").exists():
        # 人工筛选确认后，聚类/生成产物必须比确认文件新（自动重跑）
        return out.exists() and out.stat().st_mtime > (d / "selected_candidates.json").stat().st_mtime
    return out.exists()


def run_stage(card_path: str, stage: str, d: Path, force: bool):
    # -u 关闭输出缓冲；所有阶段都传 --resume，统一复用 run.py 创建的运行目录
    cmd = [sys.executable, "-u", str(SRC / f"{stage}.py"), card_path, "--resume"]
    if force and stage in ("collector", "generate"):
        cmd.append("--force")
    print(f"\n========== 阶段 {stage} 开始 ==========", flush=True)
    r = subprocess.run(cmd, cwd=str(SRC.parent))
    if r.returncode == 2:
        print(f"\n>>> {stage} 需要人工确认：请查看清单并填写对应的 *_selected.json 后重跑", flush=True)
        sys.exit(2)
    if r.returncode != 0:
        sys.exit(f"阶段 {stage} 失败，退出码 {r.returncode}（已产生的中间结果保留，--resume 可继续）")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--only", choices=STAGES + OPTIONAL, help="只跑指定阶段")
    ap.add_argument("--resume", action="store_true", help="沿用上一次运行目录")
    ap.add_argument("--force", action="store_true", help="重跑 collector/generate")
    args = ap.parse_args()

    card = load_card(args.card)
    d = run_dir(card, resume=args.resume)
    setup_log(d / "run.log")
    print(f"本次运行目录: {d}", flush=True)

    stages = [args.only] if args.only else STAGES
    for st in stages:
        if is_done(d, st) and not (args.force and st in ("collector", "generate")):
            print(f"[跳过] {st}：产物已存在")
            continue
        run_stage(args.card, st, d, args.force)

    print(f"\n全部完成。产物目录: {d}")


if __name__ == "__main__":
    main()
