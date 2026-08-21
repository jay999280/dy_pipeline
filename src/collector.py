# -*- coding: utf-8 -*-
"""① 采集：Playwright 拦截抖音网页版接口，拿结构化视频数据。

对标账号主页 → 拦截 /aweme/v1/web/aweme/post/
关键词搜索   → 拦截 /aweme/v1/web/general/search/single/
登录态保存在 data/browser_profile，首次运行需扫码。
"""
import asyncio
import json
import logging
import random
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

from common import DATA, UA, load_card, run_dir, write_json

log = logging.getLogger(__name__)

# 搜索接口有两种路径（新版 search/item 与旧版 general/search），都匹配
SEARCH_MARKS = ("aweme/v1/web/search/item", "aweme/v1/web/general/search")
POST_API = "aweme/v1/web/aweme/post"
DETAIL_API = "aweme/v1/web/aweme/detail"     # 详情页兜底（进入详情时顺手记录）
CAPTCHA_MARK = ("captcha/get", "verifycenter")  # 滑块验证码标志
PROFILE_DIR = DATA / "browser_profile"


def _extract_awemes(data: dict) -> list:
    """从接口响应里提取视频对象列表（搜索/主页/详情三种结构）。"""
    if not isinstance(data, dict):
        return []
    # 详情接口：aweme_detail 直接是视频对象
    ad = data.get("aweme_detail")
    if isinstance(ad, dict) and ad.get("aweme_id"):
        return [ad]
    for key in ("data", "aweme_list"):
        v = data.get(key)
        if not isinstance(v, list):
            continue
        out = []
        for x in v:
            if isinstance(x.get("aweme_info"), dict):
                x = x["aweme_info"]
            if isinstance(x, dict) and x.get("aweme_id"):
                out.append(x)
        return out
    return []


def _pick_video(video: dict) -> str:
    """优先取无水印播放地址，拿不到退回带水印地址。"""
    for key in ("play_addr_h264", "play_addr"):
        addr = video.get(key) or {}
        urls = addr.get("url_list") or []
        if urls:
            return urls[-1]
    return ""


class DouyinCollector:
    def __init__(self, card: dict):
        self.card = card
        self.seen = {}          # aweme_id -> record
        self.src_count = 0      # 当前来源已采条数
        self.debug_urls = []    # 诊断：相关请求 URL
        self.captcha_seen = False
        self.captcha_count = 0
        self.current_source_url = ""
        self.current_source_kw = ""
        self.min_likes = int(card.get("采集设置", {}).get("最低点赞", 0))
        self.max_per_source = int(card.get("采集设置", {}).get("每个来源最多视频数", 20))
        self.max_scrolls = int(card.get("采集设置", {}).get("滚动上限", 15))

    def _add_record(self, aw: dict, source: str):
        """把接口返回的视频对象转成统一记录。"""
        aid = aw.get("aweme_id")
        if not aid or str(aid) in self.seen:
            return
        stats = aw.get("statistics") or {}
        video = aw.get("video") or {}
        author = aw.get("author") or {}
        self.seen[str(aid)] = {
            "aweme_id": str(aid),
            "desc": aw.get("desc", ""),
            "author": author.get("nickname", ""),
            "sec_uid": author.get("sec_uid", ""),
            "digg_count": stats.get("digg_count", 0),
            "comment_count": stats.get("comment_count", 0),
            "share_count": stats.get("share_count", 0),
            "play_count": stats.get("play_count", 0),
            "duration_ms": video.get("duration", 0),
            "create_time": aw.get("create_time", 0),
            "play_url": _pick_video(video),
            "source": source,
            "source_url": self.current_source_url,
            "source_kw": self.current_source_kw,
            "url": f"https://www.douyin.com/video/{aid}",
        }
        self.src_count += 1
        log.info("  + [%s] %s | %s | 赞%s 评%s",
                 self.current_source_key, aid, aw.get("desc", "")[:40],
                 stats.get("digg_count", 0), stats.get("comment_count", 0))

    def _walk_awemes(self, node):
        """递归遍历任意 JSON 结构，产出所有含 aweme_id+desc 的对象。"""
        if isinstance(node, dict):
            if node.get("aweme_id") and node.get("desc") is not None:
                yield node
            for v in node.values():
                yield from self._walk_awemes(v)
        elif isinstance(node, list):
            for v in node:
                yield from self._walk_awemes(v)

    async def _harvest_router_data(self, page):
        """兜底：接口拦截为空时，从页面 SSR 数据 window._ROUTER_DATA 里挖视频。"""
        try:
            raw = await page.evaluate("JSON.stringify(window._ROUTER_DATA || {})")
            data = json.loads(raw)
            for aw in self._walk_awemes(data):
                self._add_record(aw, "router_data")
        except Exception as e:
            log.warning("router_data 兜底提取失败: %s", e)

    async def _on_response(self, resp):
        url = resp.url
        if any(m in url for m in SEARCH_MARKS):
            source = "search"
        elif POST_API in url:
            source = "profile"
        elif DETAIL_API in url:
            source = "detail"
        else:
            if any(m in url for m in CAPTCHA_MARK):
                self.captcha_seen = True
            # 诊断：记录一切相关请求（验证、风控、其他 aweme 接口）
            if any(k in url for k in ("aweme", "captcha", "verify", "passport", "security")):
                self.debug_urls.append(f"{resp.status} {url[:200]}")
            return
        try:
            data = await resp.json()
        except Exception:
            return
        aws = _extract_awemes(data)
        if not aws:
            # 诊断：命中接口但没解析出视频时，记录响应顶层结构
            self.debug_urls.append(
                f"[empty] {url[:120]} keys={list(data.keys())[:8] if isinstance(data, dict) else type(data)}")
            return
        for aw in aws:
            self._add_record(aw, source)

    async def _scroll_until(self, page, stop):
        """随机化滚动列表，直到 stop() 为 True 或连续无新增；遇验证码暂停等人工处理。"""
        no_new = 0
        for _ in range(self.max_scrolls):
            if self.captcha_seen:
                self.captcha_seen = False
                self.captcha_count += 1
                log.warning("检测到滑块验证码（第%d次）！请在 Chrome 窗口完成滑动验证，程序等待 20 秒...",
                            self.captcha_count)
                try:
                    await page.screenshot(path=str(self.out_dir / "captcha.png"))
                except Exception:
                    pass
                await asyncio.sleep(20)
                log.info("验证码等待结束，继续采集")
            if stop():
                return
            before = len(self.seen)
            await page.mouse.wheel(0, random.randint(800, 1500))
            await asyncio.sleep(random.uniform(1.8, 3.2))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(0.8, 1.6))
            if len(self.seen) == before:
                no_new += 1
                if no_new >= 3:
                    break
            else:
                no_new = 0

    async def _collect_profile(self, page, url: str):
        self.current_source_key = f"主页:{url[-24:]}"
        self.current_source_url = url
        self.current_source_kw = ""
        self.src_count = 0
        log.info("采集对标账号主页: %s", url)
        page.on("response", self._on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._scroll_until(
            page, stop=lambda: self.src_count >= self.max_per_source
        )
        page.remove_listener("response", self._on_response)
        if self.src_count == 0:
            await self._harvest_router_data(page)
            log.info("[%s] 接口拦截 0 条，router_data 兜底后共 %d 条",
                     self.current_source_key, self.src_count)

    async def _collect_search(self, page, kw: str):
        self.current_source_key = f"搜索:{kw}"
        self.current_source_url = ""
        self.current_source_kw = kw
        self.src_count = 0
        log.info("搜索关键词: %s", kw)
        url = f"https://www.douyin.com/search/{quote(kw)}?type=video"
        page.on("response", self._on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        await self._scroll_until(
            page, stop=lambda: self.src_count >= self.max_per_source
        )
        page.remove_listener("response", self._on_response)
        if self.src_count == 0:
            await self._harvest_router_data(page)
            log.info("[%s] 接口拦截 0 条，router_data 兜底后共 %d 条",
                     self.current_source_key, self.src_count)

    def _save_partial(self, partial: Path):
        """增量落盘已采数据（断点续传）。"""
        try:
            items = sorted(self.seen.values(), key=lambda x: -x.get("digg_count", 0))
            partial.write_text(json.dumps({"视频": items}, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        except Exception:
            pass

    async def run(self, out_json: Path) -> dict:
        self.out_dir = out_json.parent
        partial = out_json.with_suffix(".partial.json")
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        # 断点续传：预热已采数据（采集中途崩溃可续）
        if partial.exists():
            try:
                prev = json.loads(partial.read_text(encoding="utf-8"))
                for v in prev.get("视频", []):
                    if v.get("aweme_id"):
                        self.seen[str(v["aweme_id"])] = v
                log.info("断点续传：预热 %d 条已采数据", len(self.seen))
            except Exception:
                pass
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                channel="chrome",
                viewport={"width": 1440, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()

            # ---- 登录检查 ----
            await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            cookies = await browser.cookies("https://www.douyin.com")
            logged_in = any(
                c["name"] in ("sessionid", "sessionid_ss") and c["value"]
                for c in cookies
            )
            if not logged_in:
                print("\n>>> 请在弹出的 Chrome 窗口扫码登录抖音（最多等待 10 分钟）...", flush=True)
                for _ in range(300):
                    await asyncio.sleep(2)
                    cookies = await browser.cookies("https://www.douyin.com")
                    if any(c["name"] in ("sessionid", "sessionid_ss") and c["value"] for c in cookies):
                        logged_in = True
                        break
                if not logged_in:
                    log.warning("未检测到登录态，继续以游客身份采集（可能被风控/数据不完整）")
                else:
                    log.info("检测到登录态，继续采集")

            # ---- 按需求卡采集 ----
            for src_url in self.card.get("对标账号") or []:
                src_url = str(src_url).strip()
                if src_url:
                    await self._collect_profile(page, src_url)
                    self._save_partial(partial)

            for kw in self.card.get("关键词") or []:
                kw = str(kw).strip()
                if kw:
                    await self._collect_search(page, kw)
                    self._save_partial(partial)

            await browser.close()

        # ---- 汇总落盘 ----
        items = sorted(self.seen.values(), key=lambda x: -x["digg_count"])
        for it in items:
            it["recommend"] = it["digg_count"] >= self.min_likes
        summary = {
            "客户": self.card.get("客户"),
            "采集时间": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "最低点赞": self.min_likes,
            "总数": len(items),
            "推荐数": sum(1 for i in items if i["recommend"]),
            "视频": items,
        }
        write_json(out_json, summary)
        log.info("采集完成：共 %d 条，其中 %d 条达到最低点赞 %d",
                 len(items), summary["推荐数"], self.min_likes)
        if self.debug_urls:
            dbg = out_json.with_suffix(".debug_urls.txt")
            dbg.write_text("\n".join(self.debug_urls), encoding="utf-8")
            log.info("诊断请求记录已保存: %s（%d 条）", dbg, len(self.debug_urls))
        return summary


# 评论接口（用于评论区挖掘）
COMMENT_MARKS = ("comment/list", "comment/list/reply")


def _extract_comments(data: dict) -> list:
    """从评论接口响应提取评论列表：[{"text","赞","回复数"}]。"""
    out = []
    if not isinstance(data, dict):
        return out
    comments = data.get("comments")
    if comments is None:
        comments = data.get("data")
    if not isinstance(comments, list):
        return out
    for c in comments:
        if not isinstance(c, dict):
            continue
        text = c.get("text", "")
        if not text:
            continue
        out.append({
            "text": text,
            "赞": c.get("digg_count", 0) or 0,
            "回复数": c.get("reply_comment_total", 0) or c.get("reply_count", 0) or 0,
        })
    return out


async def collect_comments(video_ids: list, out_dir: Path, max_per: int = 30):
    """对给定视频列表采集评论区，落 comments/<vid>.json（断点续跑）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, channel="chrome",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        for vid in video_ids:
            jso = out_dir / f"{vid}.json"
            if jso.exists():
                continue
            comments = []

            async def _on_resp(resp):
                if any(m in resp.url for m in COMMENT_MARKS):
                    try:
                        d = await resp.json()
                        comments.extend(_extract_comments(d))
                    except Exception:
                        pass

            page.on("response", _on_resp)
            try:
                await page.goto(f"https://www.douyin.com/video/{vid}",
                                wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3)
                for _ in range(8):
                    await page.mouse.wheel(0, random.randint(800, 1500))
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                    if len(comments) >= max_per:
                        break
            finally:
                page.remove_listener("response", _on_resp)
            # 去重
            seen, uniq = set(), []
            for c in comments:
                if c["text"] not in seen:
                    seen.add(c["text"])
                    uniq.append(c)
            write_json(jso, uniq[:max_per])
            log.info("评论采集 %s: %d 条", vid, len(uniq[:max_per]))
        await browser.close()


def main():
    import argparse
    from common import setup_log

    ap = argparse.ArgumentParser()
    ap.add_argument("card", help="需求卡 yaml 路径")
    ap.add_argument("--resume", action="store_true", help="兼容 run.py 调用")
    ap.add_argument("--fresh", action="store_true", help="新建运行目录（不复用上次）")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    card = load_card(args.card)
    d = run_dir(card, resume=not args.fresh)
    setup_log(d / "run.log")

    out = d / "candidates.json"
    if out.exists() and not args.force:
        log.info("candidates.json 已存在，跳过采集（--force 重跑）")
        return
    asyncio.run(DouyinCollector(card).run(out))


if __name__ == "__main__":
    main()
