"""summary: 浏览器自动化服务

description:
  常驻 HTTP 服务，提供 Playwright 浏览器自动化 API。
  支持页面渲染、截图、导航、点击、输入、JS 执行、cookie 管理。
  所有操作共享同一个 browser context（cookie/session 自动保持）。

  启动方式（detach 模式）:
    setsid timeout -k 5 3600 $PYTHON_CMD $SHARED_DIR/scripts/web_render_server.py --port 8888 > $TASK_DIR/browser_server.log 2>&1 &
    echo $! > $TASK_DIR/browser_server.pid

  调用方式（agent 用 curl）:
    curl -s http://localhost:8888/health
    curl -s http://localhost:8888/render -d '{"url":"https://example.com","format":"markdown"}'

usage:
  $PYTHON_CMD $SHARED_DIR/scripts/web_render_server.py [--port 8888] [--host 127.0.0.1]

level: intermediate

packages: playwright, markdownify
"""

import argparse
import json
import sys
import threading
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright 未安装。请运行 detect_env.py 安装依赖", file=sys.stderr)
    sys.exit(1)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)

IDLE_TIMEOUT = 600  # 10 分钟无请求自动关闭


class BrowserManager:
    """管理 Playwright 浏览器生命周期。所有操作共享同一个 context。
    交互 API（/navigate /click /type 等）共享同一个活跃 page。"""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None  # 活跃 page（交互 API 用）
        self._last_activity = time.time()
        self._server = None  # HTTPServer 引用（空闲关闭用）

    def touch(self):
        """更新活跃时间（每次请求调用）。"""
        self._last_activity = time.time()

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._new_context()

    def stop(self):
        self._page = None
        for closer in (self._context, self._browser, self._playwright):
            if closer:
                try:
                    closer.close()
                except Exception:
                    pass
        self._context = self._browser = self._playwright = None

    def _new_context(self):
        self._context = self._browser.new_context(
            user_agent=DEFAULT_UA, viewport={"width": 1280, "height": 720}
        )
        self._page = None  # 新 context 没有活跃 page

    def ensure_alive(self):
        """浏览器崩溃则重启。"""
        try:
            if self._browser and self._browser.is_connected():
                return
        except Exception:
            pass
        self.stop()
        self.start()

    def reset(self):
        """重置 context（关闭旧的，创建新的，清空 cookie/session/page）。"""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        self._new_context()

    def get_page(self):
        """获取活跃 page（不存在则创建）。交互 API 用。"""
        self.ensure_alive()
        if self._page is None or self._page.is_closed():
            self._page = self._context.new_page()
        return self._page

    def close_page(self):
        """关闭活跃 page。"""
        if self._page and not self._page.is_closed():
            try:
                self._page.close()
            except Exception:
                pass
        self._page = None

    @property
    def context(self):
        self.ensure_alive()
        return self._context


browser_mgr = BrowserManager()


def _render_content(page, fmt):
    """从 page 提取内容。"""
    if fmt == "markdown":
        try:
            from markdownify import markdownify as md
            return md(page.content())
        except ImportError:
            return page.inner_text("body")
    if fmt == "text":
        return page.inner_text("body")
    return page.content()


class RenderHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。单线程串行。"""

    protocol_version = "HTTP/1.1"

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def log_message(self, fmt, *args):
        print(f"[{self.command} {self.path}] {fmt % args}", file=sys.stderr)

    # ─── GET ──────────────────────────────────────────────

    def do_GET(self):
        browser_mgr.touch()
        if self.path == "/health":
            alive = (
                browser_mgr._browser is not None
                and browser_mgr._browser.is_connected()
            )
            self._send_json({"status": "ok", "browser": alive})
        else:
            self._send_json({"success": False, "error": f"unknown GET endpoint: {self.path}"}, 404)

    # ─── POST ─────────────────────────────────────────────

    def do_POST(self):
        browser_mgr.touch()
        body = self._read_body()
        if body is None:
            self._send_json({"success": False, "error": "invalid JSON body"})
            return

        handlers = {
            "/render": self._handle_render,
            "/screenshot": self._handle_screenshot,
            "/navigate": self._handle_navigate,
            "/click": self._handle_click,
            "/type": self._handle_type,
            "/submit": self._handle_submit,
            "/content": self._handle_content,
            "/execute": self._handle_execute,
            "/cookies": self._handle_cookies,
            "/reset": self._handle_reset,
        }
        handler = handlers.get(self.path)
        if handler:
            handler(body)
        else:
            self._send_json({"success": False, "error": f"unknown POST endpoint: {self.path}"}, 404)

    # ─── /render ──────────────────────────────────────────

    def _handle_render(self, params):
        url = params.get("url")
        if not url:
            self._send_json({"success": False, "error": "url is required"})
            return
        fmt = params.get("format", "markdown")
        timeout = min(max(params.get("timeout", 30), 5), 120) * 1000
        wait_selector = params.get("wait_selector")

        page = None
        try:
            page = browser_mgr.context.new_page()
            resp = page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout)
            content = _render_content(page, fmt)
            self._send_json({
                "success": True,
                "url": url,
                "title": page.title(),
                "content": content,
                "content_type": fmt,
                "metadata": {
                    "status_code": resp.status if resp else None,
                    "final_url": page.url,
                },
            })
        except Exception as e:
            self._send_json({"success": False, "url": url, "error": str(e)})
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    # ─── /screenshot ──────────────────────────────────────

    def _handle_screenshot(self, params):
        url = params.get("url")
        path = params.get("path")
        if not url or not path:
            self._send_json({"success": False, "error": "url and path are required"})
            return
        full_page = params.get("full_page", False)
        timeout = min(max(params.get("timeout", 30), 5), 120) * 1000

        # path 是输出路径前缀（不含扩展名，格式由 optimize 自动决定）
        shot_dir = os.path.dirname(os.path.abspath(path))
        shot_name = os.path.splitext(os.path.basename(path))[0]

        page = None
        try:
            from image_optimize import capture_and_optimize

            page = browser_mgr.context.new_page()
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            opt = capture_and_optimize(page, shot_dir, shot_name, full_page=full_page)
            self._send_json({"success": True, "url": url, "screenshot": opt["path"],
                             "format": opt["format"], "size": opt["size"]})
        except Exception as e:
            self._send_json({"success": False, "url": url, "error": str(e)})
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass


    # ─── 交互 API（共享活跃 page）─────────────────────────

    def _handle_navigate(self, params):
        url = params.get("url")
        if not url:
            self._send_json({"success": False, "error": "url is required"})
            return
        timeout = min(max(params.get("timeout", 30), 5), 120) * 1000
        wait_until = params.get("wait_until", "domcontentloaded")
        try:
            page = browser_mgr.get_page()
            resp = page.goto(url, timeout=timeout, wait_until=wait_until)
            self._send_json({
                "success": True,
                "url": url,
                "title": page.title(),
                "final_url": page.url,
                "status_code": resp.status if resp else None,
            })
        except Exception as e:
            self._send_json({"success": False, "url": url, "error": str(e)})

    def _handle_click(self, params):
        selector = params.get("selector")
        if not selector:
            self._send_json({"success": False, "error": "selector is required"})
            return
        timeout = min(max(params.get("timeout", 30), 5), 120) * 1000
        try:
            page = browser_mgr.get_page()
            page.click(selector, timeout=timeout)
            self._send_json({"success": True, "selector": selector, "url": page.url})
        except Exception as e:
            self._send_json({"success": False, "selector": selector, "error": str(e)})

    def _handle_type(self, params):
        selector = params.get("selector")
        text = params.get("text")
        if not selector or text is None:
            self._send_json({"success": False, "error": "selector and text are required"})
            return
        try:
            page = browser_mgr.get_page()
            page.fill(selector, str(text))
            self._send_json({"success": True, "selector": selector})
        except Exception as e:
            self._send_json({"success": False, "selector": selector, "error": str(e)})

    def _handle_submit(self, params):
        selector = params.get("selector")
        timeout = min(max(params.get("timeout", 30), 5), 120) * 1000
        try:
            page = browser_mgr.get_page()
            if selector:
                page.press(selector, "Enter", timeout=timeout)
            else:
                # 无 selector → 找页面上第一个 form 提交
                page.evaluate("document.querySelector('form')?.submit()")
            page.wait_for_load_state("domcontentloaded", timeout=timeout)
            self._send_json({"success": True, "url": page.url, "title": page.title()})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)})

    def _handle_content(self, params):
        fmt = params.get("format", "markdown")
        try:
            page = browser_mgr.get_page()
            content = _render_content(page, fmt)
            self._send_json({
                "success": True,
                "url": page.url,
                "title": page.title(),
                "content": content,
                "content_type": fmt,
            })
        except Exception as e:
            self._send_json({"success": False, "error": str(e)})

    # ─── 会话管理 API ─────────────────────────────────────

    def _handle_execute(self, params):
        script = params.get("script")
        if not script:
            self._send_json({"success": False, "error": "script is required"})
            return
        try:
            page = browser_mgr.get_page()
            result = page.evaluate(script)
            self._send_json({"success": True, "result": result})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)})

    def _handle_cookies(self, params):
        """GET 语义由 do_GET 不处理 /cookies，统一走 POST。
        无 name 参数 → 获取所有 cookie；有 name+value → 设置 cookie。"""
        try:
            if "name" in params and "value" in params:
                browser_mgr.context.add_cookies([{
                    "name": params["name"],
                    "value": params["value"],
                    "domain": params.get("domain", ""),
                    "path": params.get("path", "/"),
                }])
                self._send_json({"success": True, "action": "set", "name": params["name"]})
            else:
                cookies = browser_mgr.context.cookies()
                self._send_json({"success": True, "action": "get", "cookies": cookies})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)})

    def _handle_reset(self, params):
        try:
            browser_mgr.reset()
            self._send_json({"success": True, "action": "reset", "message": "context cleared"})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)})


def _idle_watcher():
    """后台守护线程：IDLE_TIMEOUT 秒无请求 → 自动关闭服务。"""
    while True:
        time.sleep(60)
        if time.time() - browser_mgr._last_activity > IDLE_TIMEOUT:
            print(f"空闲超 {IDLE_TIMEOUT} 秒，自动关闭...", file=sys.stderr)
            if browser_mgr._server:
                browser_mgr._server.shutdown()
            return


def main():
    parser = argparse.ArgumentParser(description="浏览器自动化服务")
    parser.add_argument("--port", type=int, default=8888, help="监听端口（默认 8888）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    args = parser.parse_args()

    print("启动浏览器...", file=sys.stderr)
    browser_mgr.start()
    print("浏览器就绪", file=sys.stderr)

    server = HTTPServer((args.host, args.port), RenderHandler)
    browser_mgr._server = server
    print(f"服务监听 http://{args.host}:{args.port}", file=sys.stderr)

    # 启动空闲检测守护线程
    watcher = threading.Thread(target=_idle_watcher, daemon=True)
    watcher.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("关闭服务...", file=sys.stderr)
        server.shutdown()
        browser_mgr.stop()
        print("已关闭", file=sys.stderr)


if __name__ == "__main__":
    main()
