#!/usr/bin/env python3
"""RoboCall flag 平台验证：无头浏览器逐候选提交，监听 attempt API 判定

自包含: `state.json`（登录态）缺失时自动登录生成——需设置环境变量
  RC_USER / RC_PASS（平台账号/密码）; 登录态与截图存于本脚本同目录。
用法: ./verify_flag.py [word ...]   # 不带参数则跑内置候选列表
"""
import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE = "https://2026.sunshinectf.org"
SHOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(SHOT, "state.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"

TEMPLATE = "sun{{you_must_be_some_sort_of_nimble_{word}_navigator}}"
# space 为已平台验证的正确答案（置首，重跑者免交错误候选）; 其余为当时按语义排序的备选历史
WORDS = [
    "space",
    "queue", "frame", "phone", "trace", "route", "scope", "file",
    "code", "side", "tree", "name", "site", "race", "true", "sure",
    "like", "made", "fine", "wide", "safe", "pure", "more", "stage",
    "shape", "white", "blue", "mouse", "voice", "price",
]


def precheck_state():
    """前置检查（必须在 playwright 启动前）: state 缺失且无凭据 → 干净退出

    放在 playwright 上下文外的原因: 上下文内 SystemExit 会被 teardown 的
    TargetClosedError 异步噪音淹没，丢失错误消息与退出码。
    """
    if os.path.exists(STATE):
        return False  # 已有登录态，无需登录
    if not (os.environ.get("RC_USER") and os.environ.get("RC_PASS")):
        sys.exit(f"错误: {STATE} 不存在且未设置 RC_USER/RC_PASS 环境变量（无法自动登录）")
    return True


def ensure_state(p):
    """登录态自举: state.json 缺失时用 RC_USER/RC_PASS 登录并保存（调用前先过 precheck_state）"""
    user, pwd = os.environ["RC_USER"], os.environ["RC_PASS"]
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.fill("input[name='name']", user)
    page.fill("input[name='password']", pwd)
    page.click("input#_submit")
    page.wait_for_timeout(5000)
    if "challenges" not in page.url:
        browser.close()
        sys.exit(f"错误: 登录失败（当前 URL: {page.url}）——检查 RC_USER/RC_PASS")
    ctx.storage_state(path=STATE)
    browser.close()
    print(f"已生成登录态: {STATE}")


def run_session(p, words, verdicts):
    """一次验证会话。返回 (correct_flag 或 None, error_message 或 None)。

    注意: 本函数在 sync_playwright 上下文内执行——块内禁止 sys.exit/assert 抛错
    （会被 playwright teardown 的异步异常吞噬，丢失消息与退出码），所有失败用 return。
    """
    need_login = precheck_state()
    if need_login:
        ensure_state(p)
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900},
                              storage_state=STATE)
    page = ctx.new_page()

    api_resp = {}
    def on_resp(resp):
        if "/api/v1/challenges/attempt" in resp.url:
            try:
                api_resp["v"] = {"status": resp.status, "body": resp.json()}
            except Exception:
                api_resp["v"] = {"status": resp.status, "body": resp.text()[:200]}
    page.on("response", on_resp)

    page.goto(f"{BASE}/challenges", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4500)
    if "login" in page.url:
        return None, f"登录态失效（跳回 {page.url}）——删除 {STATE} 后重跑（将用 RC_USER/RC_PASS 重新登录）"
    card = page.query_selector("text=RoboCall")
    if not card:
        return None, f"页面上找不到 RoboCall 卡片（URL: {page.url}）——平台结构变更或登录态异常"
    card.click()
    page.wait_for_timeout(2500)

    for i, word in enumerate(words):
        flag = TEMPLATE.format(word=word)
        api_resp.clear()
        page.fill("#challenge-input", flag)
        page.click("#challenge-submit")
        page.wait_for_timeout(3000)
        v = api_resp.get("v", {})
        body = v.get("body", {}) if isinstance(v.get("body"), dict) else {}
        try:
            status = body.get("data", {}).get("status", str(body)[:80])
        except Exception:
            status = str(body)[:80]
        http = v.get("status", "?")
        print(f"[{i+1:2d}/{len(words)}] {word:8s} http={http} status={status!r}")
        verdicts.append((word, status, flag))
        if status == "correct":
            page.screenshot(path=os.path.join(SHOT, "win.png"))
            with open(os.path.join(SHOT, "result.txt"), "w") as f:
                f.write(flag + "\n")
            return flag, None
        if "authentication" in str(body).lower():
            return None, f"登录态失效（API 拒绝认证）——删除 {STATE} 后重跑"
        time.sleep(2)
    browser.close()
    return None, None


def main():
    words = sys.argv[1:] or WORDS
    verdicts = []
    with sync_playwright() as p:
        flag, err = run_session(p, words, verdicts)
    if err:
        sys.exit(f"错误: {err}")
    if flag:
        print("\n*** 正确 FLAG:", flag, "***")
        return
    with open(os.path.join(SHOT, "verdicts.json"), "w") as f:
        json.dump(verdicts, f, ensure_ascii=False, indent=1)
    print("完毕，无正确")


if __name__ == "__main__":
    main()
