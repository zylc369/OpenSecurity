#!/usr/bin/env python3
"""批量下载 writeup 源文档，HTML 转 markdown，保存到源文档库。

用法:
  python3 _download_sources.py                          # 运行硬编码列表
  python3 _download_sources.py --url <URL> --direction pwn --name file.md
  python3 _download_sources.py --github user/repo --path 2023/Dice --direction crypto
"""
import argparse
import json
import subprocess
import re
import os
import urllib.request
import ssl

from markdownify import markdownify as md
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 源文档保存目录：从脚本位置推导项目根（scripts→security-analysis-evolve→.opencode→项目根）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
SOURCE_DIR = os.path.join(PROJECT_ROOT, "docs", "资料", "writeup-sources")

# 下载源: (方向, 文件名, URL, 类型)
# raw = GitHub/GitLab raw markdown; html = 网页需转换
SOURCES = [
    # === Web 方向 ===
    ("web", "2024-googlectf-huli.md", "https://blog.huli.tw/2024/06/28/google-ctf-2024-writeup/", "html"),
    ("web", "2023-0ctf-huli.md", "https://blog.huli.tw/2023/12/11/0ctf-2023-writeup/", "html"),
    ("web", "2024-hitcon-cor-sekai-huli.md", "https://blog.huli.tw/2024/09/23/hitconctf-corctf-sekaictf-2024-writeup/", "html"),
    ("web", "2024-idekctf-iframe-huli.md", "https://blog.huli.tw/2024/09/07/idek-ctf-2024-iframe/", "html"),
    ("web", "2024-dicectf-huli.md", "https://blog.huli.tw/2024/02/12/dicectf-2024-writeup/", "html"),
    ("web", "portswigger-prototype-pollution.md", "https://portswigger.net/web-security/prototype-pollution", "html"),
    ("web", "portswigger-single-packet-attack.md", "https://portswigger.net/research/smashing-the-state-machine", "html"),
    ("web", "2025-corctf-challenge-dev-2.md", "https://www.cor.team/posts/corctf-2025-corctf-challenge-dev-2/", "html"),
    ("web", "2024-corctf-challenge-dev.md", "https://www.cor.team/posts/corctf-2024-corctf-challenge-dev/", "html"),
    ("web", "2024-sekaictf-htmlsandbox.md", "https://blog.ankursundara.com/htmlsandbox-writeup/", "html"),
    ("web", "2025-xss-no-paren-huli.md", "https://blog.huli.tw/2025/09/15/xss-without-semicolon-and-parentheses/", "html"),
    # === 逆向方向 ===
    ("reversing", "d810-readme.md", "https://gitlab.com/eshard/d810/-/raw/master/README.md", "raw"),
    ("reversing", "hex-rays-microcode-api.md", "https://www.hex-rays.com/blog/hex-rays-microcode-api-vs-obfuscating-compiler/", "html"),
    ("reversing", "hexraysdeob-readme.md", "https://raw.githubusercontent.com/RolfRolles/HexRaysDeob/master/README.md", "raw"),
    ("reversing", "goresym-readme.md", "https://raw.githubusercontent.com/mandiant/GoReSym/master/README.md", "raw"),
    ("reversing", "mandiant-golang-internals.md", "https://www.mandiant.com/resources/blog/golang-internals-symbol-recovery", "html"),
    ("reversing", "ida90-release-notes.md", "https://docs.hex-rays.com/release-notes/9_0.md", "html"),
]


def download(url, timeout=30):
    """curl 下载，返回文本或 None"""
    try:
        result = subprocess.run(
            ["curl", "-sfL", "--max-time", str(timeout),
             "-A", "Mozilla/5.0 (compatible; WriteupArchiver/1.0)", url],
            capture_output=True, timeout=timeout + 5
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return result.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def html_to_markdown(html):
    """HTML 转 markdown，先用 BeautifulSoup 清理杂讯"""
    soup = BeautifulSoup(html, "html.parser")
    # 删除所有非正文标签
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    # 尝试提取正文容器（优先级: article > main > 全文）
    container = soup.find("article") or soup.find("main") or soup
    text = md(str(container), heading_style="ATX")
    text = re.sub(r'\n{4,}', '\n\n\n', text)  # 压缩连续空行
    return text.strip()


def main():
    success, failed = 0, 0
    for direction, filename, url, source_type in SOURCES:
        label = f"{direction}/{filename}"
        print(f"  {label} ...", end=" ", flush=True)

        content = download(url)
        if content is None:
            print("❌ 下载失败")
            failed += 1
            continue

        if source_type == "html":
            content = html_to_markdown(content)

        dir_path = os.path.join(SOURCE_DIR, direction)
        os.makedirs(dir_path, exist_ok=True)
        filepath = os.path.join(dir_path, filename)

        header = f"---\n来源: {url}\n类型: {source_type}\n获取日期: 2026-06-29\n---\n\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + content)

        print(f"✅ {len(content)} chars")
        success += 1

    print(f"\n完成: {success} 成功, {failed} 失败")


def save_source(direction, filename, url, content, source_type):
    """保存源文档到对应方向目录，加 YAML 头部。"""
    dir_path = os.path.join(SOURCE_DIR, direction)
    os.makedirs(dir_path, exist_ok=True)
    filepath = os.path.join(dir_path, filename)
    header = f"---\n来源: {url}\n类型: {source_type}\n获取日期: 2026-06-30\n---\n\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(header + content)
    return len(content)


def download_single(url, direction, name):
    """下载单个 URL 并保存。"""
    print(f"  下载 {url} ...", end=" ", flush=True)
    content = download(url)
    if content is None:
        print("❌ 下载失败")
        return False
    is_html = not url.endswith((".c", ".py", ".sage", ".md"))
    source_type = "html" if is_html else "raw"
    if is_html:
        content = html_to_markdown(content)
    size = save_source(direction, name, url, content, source_type)
    print(f"✅ {size} chars")
    return True


def download_github_dir(repo, path, direction):
    """下载 GitHub 仓库某目录下的 .py/.sage/.md 文件。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    print(f"  获取 {repo}/{path} 目录结构 ...")
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            files = json.loads(resp.read())
    except Exception as e:
        print(f"❌ API 失败: {e}")
        return
    if not isinstance(files, list):
        print(f"❌ 非预期响应: {files}")
        return
    for f in files:
        fname = f.get("name", "")
        dl_url = f.get("download_url")
        if not dl_url or not fname.endswith((".py", ".sage", ".md")):
            continue
        label = path.replace("/", "-")
        outfile = f"{repo.split('/')[0]}-{label}-{fname}"
        print(f"  下载 {fname} ...", end=" ", flush=True)
        content = download(dl_url)
        if content is None:
            print("❌")
            continue
        size = save_source(direction, outfile, dl_url, content, "raw")
        print(f"✅ {size} chars")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="下载 writeup 源文档")
    parser.add_argument("--url", help="下载单个 URL")
    parser.add_argument("--direction", default="misc", help="保存方向子目录")
    parser.add_argument("--name", help="保存文件名（--url 模式）")
    parser.add_argument("--github", help="GitHub 仓库 (user/repo)")
    parser.add_argument("--path", help="GitHub 仓库内路径（--github 模式）")
    args = parser.parse_args()

    if args.url:
        if not args.name:
            print("❌ --url 模式需要 --name 参数")
            exit(1)
        download_single(args.url, args.direction, args.name)
    elif args.github:
        if not args.path:
            print("❌ --github 模式需要 --path 参数")
            exit(1)
        download_github_dir(args.github, args.path, args.direction)
    else:
        main()
