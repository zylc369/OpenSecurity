"""summary: Web 安全分析公共工具库

description:
  封装 Web 安全分析中的高频操作（HTTP session 管理、CSRF 提取、注册登录、
  webhook.site 交互）。每个函数可独立使用，不强制组合调用。

  依赖: requests, beautifulsoup4, lxml（通过 $PYTHON_CMD 调用）

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from web_helpers import create_session, get_csrf, register_and_login

usage:
  作为库模块被 import，不作为命令行工具使用。

level: intermediate
"""

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
