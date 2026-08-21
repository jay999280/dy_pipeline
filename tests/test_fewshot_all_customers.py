# -*- coding: utf-8 -*-
"""三个客户脚本文件格式兼容性检查。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from generate import parse_fewshot_xlsx

files = {
    "示例": r"示例脚本.xlsx",
    "凯恩怡家": r"凯恩怡家脚本0506.xlsx",
    "钢栈桥": r"钢栈桥脚本7.29.xlsx",
}
for name, path in files.items():
    ex = parse_fewshot_xlsx(path)
    print(f"{name}: {len(ex)} 组 |", " / ".join(f"{e['发布文案'][:18]}…{len(e['镜头'])}镜" for e in ex[:4]))
