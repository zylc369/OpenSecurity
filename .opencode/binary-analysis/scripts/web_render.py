"""summary: Playwright 网页渲染脚本

description:
  使用 Playwright 无头浏览器渲染网页，支持 JavaScript 执行。
  当 webfetch 无法获取 SPA 页面内容时使用本脚本。
  支持渲染内容提取（markdown/text/html）和页面截图。

usage:
  $PYTHON_CMD $SHARED_DIR/scripts/web_render.py --url URL [--format FORMAT] [--screenshot PATH] [选项]

level: intermediate

packages: playwright, markdownify
"""

import argparse
import json
import sys


def render_page(url, fmt="markdown", screenshot=None, screenshot_full_page=False,
                timeout=30, wait_selector=None, user_agent=None):
    """渲染网页并提取内容。返回结果字典。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"success": False, "error": "playwright 未安装。请运行 detect_env.py 安装依赖"}

    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "URL 必须以 http:// 或 https:// 开头"}

    timeout_ms = min(max(timeout, 5), 120) * 1000
    result = {"success": False, "url": url}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=user_agent or (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 720},
                )
                page = context.new_page()

                # 导航到目标页面
                response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                status_code = response.status if response else None
                final_url = page.url

                # 等待额外条件
                if wait_selector:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                else:
                    # 默认等待网络空闲（SPA 内容加载完成）
                    try:
                        page.wait_for_load_state("networkidle", timeout=timeout_ms)
                    except Exception:
                        pass  # 超时不致命，继续提取已有内容

                # 提取页面标题
                title = page.title()

                # 提取内容
                content = ""
                content_type = fmt
                if fmt == "markdown":
                    raw_html = page.content()
                    content = _html_to_markdown(raw_html)
                elif fmt == "text":
                    content = page.inner_text("body")
                elif fmt == "html":
                    content = page.content()

                # 截图
                screenshot_path = None
                if screenshot:
                    page.screenshot(path=screenshot, full_page=screenshot_full_page)
                    screenshot_path = screenshot
            finally:
                browser.close()

            result.update({
                "success": True,
                "title": title,
                "content": content,
                "content_type": content_type,
                "screenshot": screenshot_path,
                "metadata": {
                    "status_code": status_code,
                    "final_url": final_url,
                },
            })

    except Exception as e:
        result["error"] = str(e)

    return result


def _html_to_markdown(html):
    """HTML → Markdown 转换，使用 markdownify 库。"""
    from markdownify import markdownify
    return markdownify(html, heading_style="ATX", code_language="")


def main():
    parser = argparse.ArgumentParser(description="Playwright 网页渲染工具")
    parser.add_argument("--url", required=True, help="目标 URL（必须 http:// 或 https://）")
    parser.add_argument("--format", choices=["markdown", "text", "html"], default="markdown",
                        help="输出格式（默认 markdown）")
    parser.add_argument("--screenshot", help="截图保存路径（JPEG/PNG 由扩展名决定）")
    parser.add_argument("--screenshot-full-page", action="store_true", help="全页截图（默认仅视口）")
    parser.add_argument("--timeout", type=int, default=30, help="渲染超时秒数（默认 30，最大 120）")
    parser.add_argument("--wait-selector", help="等待特定 CSS 选择器出现")
    parser.add_argument("--output", help="JSON 输出路径（不指定则 stdout）")
    parser.add_argument("--user-agent", help="自定义 User-Agent")
    args = parser.parse_args()

    result = render_page(
        url=args.url,
        fmt=args.format,
        screenshot=args.screenshot,
        screenshot_full_page=args.screenshot_full_page,
        timeout=args.timeout,
        wait_selector=args.wait_selector,
        user_agent=args.user_agent,
    )

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        import os
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
    else:
        sys.stdout.buffer.write(output_json.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
