# -*- coding: utf-8 -*-
"""采集器解析逻辑单元测试：用三种接口结构的合成数据验证。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from collector import _extract_awemes, _pick_video

# 搜索接口结构
search = {
    "data": [
        {"aweme_id": "111", "desc": "搜索视频",
         "aweme_info": None,
         "author": {"nickname": "A"}, "statistics": {"digg_count": 100}},
        {"aweme_info": {"aweme_id": "222", "desc": "嵌套aweme_info",
                        "author": {"nickname": "B"}, "statistics": {"digg_count": 200}}},
    ]
}
# 主页接口结构
profile = {
    "aweme_list": [
        {"aweme_id": "333", "desc": "主页视频",
         "video": {"play_addr": {"url_list": ["https://x/playwm", "https://x/play"]}},
         "author": {"nickname": "C"}, "statistics": {"digg_count": 300}},
    ]
}
# 详情接口结构
detail = {"aweme_detail": {"aweme_id": "444", "desc": "详情视频"}}

assert len(_extract_awemes(search)) == 2, "搜索结构解析失败"
assert len(_extract_awemes(profile)) == 1, "主页结构解析失败"
assert len(_extract_awemes(detail)) == 1, "详情结构解析失败"
assert _pick_video(profile["aweme_list"][0]["video"]) == "https://x/play", "应优先无水印地址"
assert _extract_awemes({"data": "notalist"}) == []
assert _extract_awemes({}) == []
print("collector 解析逻辑测试全部通过")
