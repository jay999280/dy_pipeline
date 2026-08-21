# -*- coding: utf-8 -*-
"""few-shot xlsx 解析器测试：用真实的示例脚本文件验证。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from generate import parse_fewshot_xlsx

examples = parse_fewshot_xlsx(r"示例脚本.xlsx")
print(f"解析到 {len(examples)} 组脚本")
for i, e in enumerate(examples):
    shots = len(e["镜头"])
    print(f"--- [{i}] 发布文案: {e['发布文案'][:50]} | 镜头数: {shots}")
    if shots:
        print("    首镜:", e["镜头"][0]["画面"][:24], "|", e["镜头"][0]["文案"][:44])
        print("    末镜:", e["镜头"][-1]["画面"][:24], "|", e["镜头"][-1]["文案"][:44])
