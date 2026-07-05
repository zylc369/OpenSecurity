"""summary: Sploitus 漏洞/exploit 搜索工具

description:
  调用 Sploitus API 搜索公开的漏洞和 exploit。
  Sploitus 是免费的漏洞/exploit 搜索引擎，不需要 API key。
  支持 exploits 和 tools 两种搜索类型。

usage:
  $PYTHON_CMD $SHARED_DIR/scripts/sploitus_search.py "Apache 2.4.49"
  $PYTHON_CMD $SHARED_DIR/scripts/sploitus_search.py "CVE-2024-1234" --type exploits
  $PYTHON_CMD $SHARED_DIR/scripts/sploitus_search.py "redis" --limit 5 --output $TASK_DIR/results.json

level: intermediate

packages: requests
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print(json.dumps({"success": False, "error": "requests 未安装。请运行 detect_env.py 安装依赖"}))
    sys.exit(1)

SPLOITUS_API_URL = "https://sploitus.com/search"
DEFAULT_TIMEOUT = 30
DEFAULT_LIMIT = 10
MAX_LIMIT = 25


def search(query, exploit_type="exploits", sort="default", limit=DEFAULT_LIMIT, offset=0):
    """搜索 Sploitus。返回结果字典。"""
    limit = max(1, min(limit, MAX_LIMIT))

    req_body = {
        "query": query,
        "type": exploit_type,
        "sort": sort,
        "title": False,
        "offset": offset,
    }

    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://sploitus.com",
        "Referer": f"https://sploitus.com/?query={query.replace(' ', '+')}",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
    }

    try:
        resp = requests.post(
            SPLOITUS_API_URL, json=req_body, headers=headers, timeout=DEFAULT_TIMEOUT
        )
    except requests.exceptions.Timeout:
        return {"success": False, "error": f"请求超时（{DEFAULT_TIMEOUT}秒）"}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"网络连接失败: {e}"}

    if resp.status_code == 429:
        return {"success": False, "error": "Sploitus API 速率限制，请稍后重试"}
    if resp.status_code == 499:
        return {"success": False, "error": "Sploitus API 临时限流，请稍后重试"}
    if resp.status_code != 200:
        return {"success": False, "error": f"Sploitus API 返回 HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return {"success": False, "error": "Sploitus API 返回的 JSON 解析失败"}

    exploits = data.get("exploits", [])
    total = data.get("exploits_total", 0)

    results = []
    for exp in exploits[:limit]:
        results.append({
            "title": exp.get("title", ""),
            "type": exp.get("type", ""),
            "href": exp.get("href", ""),
            "id": exp.get("id", ""),
        })

    return {
        "success": True,
        "query": query,
        "type": exploit_type,
        "total_matches": total,
        "returned": len(results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Sploitus 漏洞/exploit 搜索")
    parser.add_argument("query", help="搜索关键词（如 'Apache 2.4.49' 或 'CVE-2024-1234'）")
    parser.add_argument("--type", default="exploits", choices=["exploits", "tools"],
                        help="搜索类型: exploits（默认）或 tools")
    parser.add_argument("--sort", default="default", help="排序方式（默认 default）")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"返回结果数（默认 {DEFAULT_LIMIT}，最大 {MAX_LIMIT}）")
    parser.add_argument("--offset", type=int, default=0, help="结果偏移（分页）")
    parser.add_argument("--output", help="输出到文件（默认 stdout）")
    args = parser.parse_args()

    result = search(args.query, args.type, args.sort, args.limit, args.offset)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
