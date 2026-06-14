"""summary: Bot server.js 自动分析工具

description:
  解析 Web CTF 中 Puppeteer Bot 的 server.js 代码，自动提取关键参数、
  分类 Bot 模式、生成攻击时间线分析。

  功能：
  1. 提取 Bot 关键参数（flag 来源、内部 URL、超时、浏览器配置）
  2. 分类 Bot 模式（单页 vs 双页）
  3. 生成攻击时间线分析
  4. 输出攻击策略建议

  依赖: 无第三方依赖

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from bot_analyze import analyze_bot_file, BotPattern

usage:
  直接运行: python bot_analyze.py <server.js 文件路径>

level: intermediate
"""

import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class BotPattern(Enum):
    """Bot 行为模式"""
    SINGLE_PAGE = "single-page"   # 单页模式：一个 page，goto 前设置 flag
    TWO_PAGE = "two-page"         # 双页模式：firstPage 访问 URL，secondPage 保存 flag
    UNKNOWN = "unknown"


@dataclass
class BotAnalysis:
    """Bot 分析结果"""
    # 基本信息
    flag_env_var: str = ""                          # FLAG 环境变量名
    flag_default: str = ""                          # FLAG 默认值
    challenge_url: str = ""                         # CHALLENGE_URL
    challenge_url_default: str = ""                 # CHALLENGE_URL 默认值
    bot_port: int = 3000                            # Bot 端口
    max_concurrent: int = 10                        # 最大并发
    browser_executable: str = ""                    # 浏览器可执行文件路径

    # 模式分析
    pattern: BotPattern = BotPattern.UNKNOWN        # Bot 模式
    page_count: int = 0                             # newPage() 调用次数
    goto_timeout: int = 10000                       # goto 超时（毫秒）
    wait_after_goto: int = 0                        # goto 后等待时间（毫秒）

    # Flag 分析
    flag_location: str = ""                         # cookie / localStorage / dom / unknown
    flag_http_only: bool = True                     # Cookie httpOnly
    flag_cookie_url: str = ""                       # Cookie 绑定的 URL
    flag_cookie_path: str = "/"                     # Cookie Path

    # 攻击建议
    attack_strategy: List[str] = field(default_factory=list)
    timeline_events: List[str] = field(default_factory=list)

    # 原始代码片段
    raw_code: str = ""

    def report(self) -> str:
        """生成分析报告。"""
        lines = []
        lines.append("=" * 60)
        lines.append("Bot server.js 分析报告")
        lines.append("=" * 60)

        # 基本信息
        lines.append(f"\n── 基本信息 ──")
        lines.append(f"  Flag 环境变量: {self.flag_env_var}")
        lines.append(f"  Flag 默认值:   {self.flag_default}")
        lines.append(f"  内部 URL:      {self.challenge_url_default}")
        lines.append(f"  Bot 端口:      {self.bot_port}")
        lines.append(f"  最大并发:      {self.max_concurrent}")
        lines.append(f"  浏览器:        {self.browser_executable or 'chromium (默认)'}")

        # 模式分析
        lines.append(f"\n── 模式分析 ──")
        lines.append(f"  Bot 模式:     {self.pattern.value}")
        lines.append(f"  page 数量:    {self.page_count}")
        lines.append(f"  goto 超时:    {self.goto_timeout}ms")
        lines.append(f"  等待时间:     {self.wait_after_goto}ms")

        # Flag 分析
        lines.append(f"\n── Flag 分析 ──")
        lines.append(f"  Flag 位置:    {self.flag_location}")
        if self.flag_location == "cookie":
            lines.append(f"  httpOnly:     {self.flag_http_only}")
            lines.append(f"  Cookie URL:   {self.flag_cookie_url}")
            lines.append(f"  Cookie Path:  {self.flag_cookie_path}")
        lines.append(f"  内部域名:     {self._extract_internal_host()}")

        # 攻击建议
        if self.attack_strategy:
            lines.append(f"\n── 攻击策略建议 ──")
            for i, tip in enumerate(self.attack_strategy, 1):
                lines.append(f"  {i}. {tip}")

        # 时间线
        if self.timeline_events:
            lines.append(f"\n── 攻击时间线 ──")
            for event in self.timeline_events:
                lines.append(f"  {event}")

        return "\n".join(lines)

    def _extract_internal_host(self) -> str:
        """从 CHALLENGE_URL 中提取内部主机名。"""
        url = self.challenge_url_default or self.challenge_url
        if not url:
            return "unknown"
        match = re.match(r'https?://([^/:]+)', url)
        return match.group(1) if match else url


def analyze_bot_code(code: str) -> BotAnalysis:
    """分析 Bot server.js 代码。

    Args:
        code: server.js 的源代码

    Returns:
        BotAnalysis 分析结果
    """
    result = BotAnalysis()
    result.raw_code = code

    # ── 提取 FLAG 环境变量 ──
    m = re.search(r"process\.env\.(\w+)\s*\|\|\s*['\"]([^'\"]+)['\"]", code)
    if m and 'FLAG' in m.group(1).upper():
        result.flag_env_var = m.group(1)
        result.flag_default = m.group(2)

    # ── 提取 CHALLENGE_URL ──
    m = re.search(r"CHALLENGE_URL\s*\|\|\s*['\"]([^'\"]+)['\"]", code)
    if m:
        result.challenge_url_default = m.group(1)

    m = re.search(r"CHALLENGE_URL\s*=\s*process\.env", code)
    if m:
        result.challenge_url = "process.env.CHALLENGE_URL"

    # ── 提取端口 ──
    m = re.search(r"BOT_PORT\s*\|\|\s*(\d+)", code)
    if m:
        result.bot_port = int(m.group(1))

    # ── 提取最大并发 ──
    m = re.search(r"MAX_CONCURRENT\s*\|\|\s*(\d+)", code)
    if m:
        result.max_concurrent = int(m.group(1))

    # ── 提取浏览器可执行文件 ──
    m = re.search(r"PUPPETEER_EXECUTABLE_PATH\s*\|\|\s*['\"]([^'\"]+)['\"]", code)
    if m:
        result.browser_executable = m.group(1)

    # ── 分析 page 数量 ──
    page_calls = re.findall(r"await\s+browser\.newPage\(\)", code)
    result.page_count = len(page_calls)

    # ── 分析 Bot 模式 ──
    if result.page_count == 1:
        result.pattern = BotPattern.SINGLE_PAGE
    elif result.page_count >= 2:
        result.pattern = BotPattern.TWO_PAGE

    # ── 提取 goto 超时 ──
    m = re.search(r"page\.goto\([^)]*timeout:\s*(\d+)", code)
    if m:
        result.goto_timeout = int(m.group(1))

    # ── 提取等待时间 ──
    m = re.search(r"setTimeout\(resolve,\s*(\d+)\)", code)
    if m:
        result.wait_after_goto = int(m.group(1))

    # ── 分析 flag 位置 ──
    if "setCookie" in code:
        result.flag_location = "cookie"
        # 提取 httpOnly
        m = re.search(r"httpOnly:\s*(true|false)", code)
        if m:
            result.flag_http_only = m.group(1) == "true"
        # 提取 Cookie URL（可能是字符串字面量或变量名）
        m = re.search(r"url:\s*['\"]([^'\"]+)['\"]", code)
        if m:
            result.flag_cookie_url = m.group(1)
        else:
            # 尝试匹配变量名（如 url: CHALLENGE_URL）
            m = re.search(r"url:\s*(\w+)", code)
            if m:
                var_name = m.group(1)
                # 尝试解析变量值
                m2 = re.search(rf"{var_name}\s*\|\|\s*['\"]([^'\"]+)['\"]", code)
                if m2:
                    result.flag_cookie_url = m2.group(1)
                else:
                    result.flag_cookie_url = f"<变量: {var_name}>"
        # 提取 Cookie Path
        m = re.search(r"path:\s*['\"]([^'\"]+)['\"]", code)
        if m:
            result.flag_cookie_path = m.group(1)

    elif "localStorage" in code:
        result.flag_location = "localStorage"

    elif "page.evaluate" in code and "FLAG" in code:
        result.flag_location = "dom"

    else:
        result.flag_location = "unknown"
        # 进一步分析：看 secondPage 的行为
        if result.pattern == BotPattern.TWO_PAGE:
            result.flag_location = "localStorage (推测：双页模式通常将 flag 存在 localStorage)"

    # ── 生成攻击策略 ──
    result.attack_strategy = _generate_attack_strategy(result)
    result.timeline_events = _generate_timeline(result)

    return result


def analyze_bot_file(filepath: str) -> BotAnalysis:
    """从文件分析 Bot server.js。

    Args:
        filepath: server.js 文件路径

    Returns:
        BotAnalysis 分析结果
    """
    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
    return analyze_bot_code(code)


def _generate_attack_strategy(analysis: BotAnalysis) -> List[str]:
    """根据分析结果生成攻击策略建议。"""
    strategies = []
    internal_host = analysis._extract_internal_host()

    # 基于 flag 位置
    if analysis.flag_location == "cookie":
        if not analysis.flag_http_only:
            strategies.append(f"XSS → document.cookie 读取 flag（httpOnly=false，可读）")
        else:
            strategies.append(f"XSS 无法直接读取 Cookie（httpOnly=true），需要考虑其他方式（如 CSRF）")

    elif "localStorage" in analysis.flag_location:
        strategies.append(f"XSS → localStorage.getItem() 读取 flag")

    # 基于 Bot 模式
    if analysis.pattern == BotPattern.SINGLE_PAGE:
        strategies.append(
            f"单页模式：XSS 在 page.goto() 时立即执行，时间窗口约 "
            f"{analysis.wait_after_goto / 1000:.0f} 秒"
        )
        strategies.append(
            f"Bot URL 必须使用内部域名: http://{internal_host}/path"
        )

    elif analysis.pattern == BotPattern.TWO_PAGE:
        strategies.append(
            f"双页模式：firstPage 访问攻击者 URL → firstPage.close() → "
            f"secondPage 保存 flag"
        )
        strategies.append(
            f"利用 popup 存活机制：firstPage 中 window.open() 打开的 popup "
            f"在 firstPage.close() 后仍然存活"
        )
        strategies.append(
            f"使用轮询等待 flag：popup 中 setInterval 每 500ms 检查 localStorage"
        )

    # 基于浏览器
    if "chromium" in analysis.browser_executable.lower() or not analysis.browser_executable:
        strategies.append(
            f"Docker 中使用 Chromium（非 Chrome），Accept-Encoding 可能不含 'br'（Brotli）"
        )

    # 数据外泄
    strategies.append(f"外泄方式：webhook.site（有外网）或缓存中缓存（无外网）")

    return strategies


def _generate_timeline(analysis: BotAnalysis) -> List[str]:
    """根据分析结果生成攻击时间线。"""
    events = []
    t = 0

    if analysis.pattern == BotPattern.SINGLE_PAGE:
        events.append(f"t={t:4.1f}s  browser.newPage()")
        t += 0.5

        if analysis.flag_location == "cookie":
            events.append(f"t={t:4.1f}s  page.setCookie(flag)")
            t += 0.5

        events.append(f"t={t:4.1f}s  page.goto(userUrl)  ← XSS 开始执行")
        t += 2

        events.append(f"t={t:4.1f}s  页面加载完成（networkidle2）")
        t += analysis.wait_after_goto / 1000

        events.append(f"t={t:4.1f}s  browser.close()")
        events.append(f"")
        events.append(f"XSS 时间窗口: ~{analysis.wait_after_goto / 1000:.0f} 秒")

    elif analysis.pattern == BotPattern.TWO_PAGE:
        events.append(f"t={t:4.1f}s  firstPage = browser.newPage()")
        t += 0.5

        events.append(f"t={t:4.1f}s  firstPage.goto(userUrl)  ← 攻击者 XSS 开始")
        t += 2

        events.append(f"t={t:4.1f}s  页面加载完成")
        t += analysis.wait_after_goto / 1000

        events.append(f"t={t:4.1f}s  firstPage.close()")
        events.append(f"          ↑ popup（由 firstPage 中 window.open 创建）仍然存活！")
        t += 1

        events.append(f"t={t:4.1f}s  secondPage = browser.newPage()")
        t += 1

        events.append(f"t={t:4.1f}s  registerAndLogin(secondPage)")
        t += 3

        events.append(f"t={t:4.1f}s  saveFlag(secondPage)  ← flag 写入")
        t += 1

        events.append(f"t={t:4.1f}s  secondPage.close()")
        t += 1

        events.append(f"t={t:4.1f}s  browser.close()  ← 所有窗口关闭")
        events.append(f"")
        events.append(f"popup 轮询窗口: 从 ~t=3s 到 ~t={t:.0f}s（约 {t-3:.0f} 秒）")

    return events


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python bot_analyze.py <server.js 文件路径>")
        print()
        print("示例:")
        print("  python bot_analyze.py /path/to/bot/server.js")
        sys.exit(1)

    filepath = sys.argv[1]
    try:
        analysis = analyze_bot_file(filepath)
        print(analysis.report())
    except FileNotFoundError:
        print(f"文件不存在: {filepath}")
        sys.exit(1)
    except Exception as e:
        print(f"分析失败: {e}")
        sys.exit(1)
