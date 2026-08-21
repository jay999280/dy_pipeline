# -*- coding: utf-8 -*-
"""核心纯函数单元测试（pytest）。

运行: python -m pytest tests/ -v
覆盖：需求卡校验、量化预筛、钩子判定、合规扫描、卖点覆盖、查重/结构同质化、评论提取、LLM 缓存。
"""
import json
import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from common import load_card  # noqa: E402
from video_screen import quantitative_prescreen, evaluate_screen, _median  # noqa: E402
from generate import (  # noqa: E402
    compliance_scan, sellpoint_coverage, _sp_keywords,
    structure_similarity, check_structure_dupes, check_similarity,
    _flat_openers, _cta_lib, _is_weak_hook,
)
from collector import _extract_comments  # noqa: E402
from analyze import _cache_key, _cache_get, _cache_put  # noqa: E402

CARD = str(SRC.parent / "config" / "示例_需求卡.yaml")


# ---------- 需求卡校验 ----------
def test_load_card_ok():
    card = load_card(CARD)
    assert card["客户"] == "示例客户"


def test_load_card_reject_bad_engine(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("客户: 测试\n业务简介: x\n生成设置:\n  赛道数: 3\n  每赛道脚本数: 5\n转写设置:\n  引擎: 非法\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_card(str(bad))


def test_load_card_reject_missing_field(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("客户: 测试\n业务简介: x\n生成设置:\n  赛道数: 3\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_card(str(bad))


# ---------- 量化预筛 ----------
def _v(aweme_id, author, digg, comment=0, share=0, play=0, create_time=None):
    return {"aweme_id": aweme_id, "author": author, "digg_count": digg,
            "comment_count": comment, "share_count": share, "play_count": play,
            "create_time": create_time or int(time.time())}


def test_quantitative_prescreen():
    now = int(time.time())
    one_month = 30 * 24 * 3600
    by_author = {"A": [
        _v("a1", "A", 100, create_time=now - 10 * one_month),
        _v("a2", "A", 500, create_time=now - one_month),
        _v("a3", "A", 300, create_time=now - 30 * one_month),
    ], "B": [_v("b1", "B", 50, play=0, create_time=now)]}
    videos = [v for vs in by_author.values() for v in vs]
    videos = quantitative_prescreen(videos, by_author, {"筛选设置": {}})
    m = {v["aweme_id"]: v for v in videos}
    assert abs(m["a1"]["爆款系数"] - 0.33) < 0.02
    assert abs(m["a2"]["爆款系数"] - 1.67) < 0.02
    assert m["a3"]["预筛否决"] is True
    assert m["b1"]["互动率"] is None


def test_median():
    assert _median([1, 2, 3, 4]) == 2.5
    assert _median([]) == 0.0


# ---------- 钩子判定 ----------
def test_hook_detection():
    card = load_card(CARD)
    openers = _flat_openers(card)
    assert "我是老王" in openers
    assert _is_weak_hook("我是老王今天讲橱柜", openers)
    assert not _is_weak_hook("千万别装错，坑你两万", openers)


def test_cta_lib():
    card = load_card(CARD)
    cta = _cta_lib(card)
    assert any("杭州" in c for c in cta)


# ---------- 合规扫描 / 卖点覆盖 ----------
def test_compliance_scan():
    scripts = [{"发布文案": "最好的橱柜", "镜头": [{"文案": "第一品牌，100%有效"}]},
               {"发布文案": "正常", "镜头": [{"文案": "防水防潮"}]}]
    warns = compliance_scan(scripts)
    assert len(warns) == 1 and warns[0][1] == "最好"


def test_sellpoint_coverage():
    card = {"卖点": ["304不锈钢 / 全铝防水防潮零甲醛", "报价透明免费测量", "一天装好"]}
    sb = {"A": [
        {"发布文案": "", "镜头": [{"文案": "我家柜子用304不锈钢，全铝防水防潮零甲醛"}]},
        {"发布文案": "", "镜头": [{"文案": "报价透明免费测量，没有隐形增项"}]},
    ]}
    cov = sellpoint_coverage(sb, card)
    assert cov["coverage"]["304不锈钢 / 全铝防水防潮零甲醛"] == 1
    assert cov["coverage"]["一天装好"] == 0


def test_sp_keywords():
    assert "304不锈钢" in _sp_keywords("304不锈钢 / 全铝防水防潮零甲醛")


# ---------- 查重 / 结构同质化 ----------
def test_check_similarity_plagiarism():
    warns = check_similarity([{"镜头": [{"文案": "这段是完全照抄的原文句子哦"}]}],
                             "这段是完全照抄的原文句子哦")
    assert len(warns) == 1


def test_structure_similarity():
    a = {"镜头": [{"时间": "0-3s"}, {"时间": "3-8s"}, {"时间": "8-15s"}]}
    b = {"镜头": [{"时间": "0-3s"}, {"时间": "3-8s"}, {"时间": "8-15s"}]}
    c = {"镜头": [{"时间": "0-5s"}, {"时间": "5-20s"}]}
    assert structure_similarity(a, b) > 0.9
    assert structure_similarity(a, c) < 0.8


def test_check_structure_dupes():
    a = {"镜头": [{"时间": "0-3s"}, {"时间": "3-8s"}]}
    b = {"镜头": [{"时间": "0-3s"}, {"时间": "3-8s"}]}
    dupes = check_structure_dupes({"A": [a, b]})
    assert len(dupes) == 1


# ---------- 评论提取 ----------
def test_extract_comments():
    data = {"data": [{"text": "多少钱", "digg_count": 88, "reply_comment_total": 5},
                     {"text": "", "digg_count": 10}]}
    out = _extract_comments(data)
    assert len(out) == 1 and out[0]["赞"] == 88


# ---------- LLM 缓存 ----------
def test_llm_cache(tmp_path, monkeypatch):
    import analyze
    monkeypatch.setattr(analyze, "DATA", tmp_path)
    key = _cache_key([{"role": "user", "content": "测试"}], "m", 0.3)
    _cache_put(key, {"结果": "ok"})
    assert _cache_get(key) == {"结果": "ok"}
