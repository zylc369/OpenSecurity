# writeup 素材搜索与下载指南

> 当需要从网络搜索和下载 writeup 时读取本文件。

---

## §1 获取渠道速查

| 方向 | 渠道 | URL | 获取方式 |
|------|------|-----|---------|
| Pwn 堆利用 | how2heap | `github.com/shellphish/how2heap` | curl raw `.c` 文件 |
| 内核 Pwn | ptr-yudai 博客 | `ptr-yudai.hatenablog.com` | curl HTML → BeautifulSoup |
| Web | huli 博客 | `blog.huli.tw` | 同上 |
| Web 方法论 | PortSwigger | `portswigger.net/research` | 同上 |
| 密码学 | pcw109550 | `github.com/pcw109550/write-up` | curl raw `.sage`/`.py` |
| 密码学 | rkm0959 | `github.com/rkm0959/CTFWriteups` | 同上 |
| ZKP 安全 | ZKDocs | `zkdocs.com` | curl HTML → BeautifulSoup |
| SIDH 攻击 | GiacomoPope | `github.com/GiacomoPope/Castryck-Decru-SageMath` | curl raw `.sage` |
| 逆向工具 | 各工具 README | GitHub raw（D-810/GoReSym/HexRaysDeob） | curl raw |
| 移动端 | Frida 官方 | `frida.re/news`、`docs.frida.re` | curl HTML |
| 综合索引 | CTFtime | `ctftime.org/writeups` | 搜索入口，按需定向下载 |
| 题目归档 | ctf-archives | `github.com/sajjadium/ctf-archives` | 按赛事/年份浏览 |

**不在这张表里的来源**：优先用 webfetch 搜索，找到后按 §2 方法下载。

---

## §2 下载方法

### 方法 1: GitHub raw（纯文本，最简单）
```bash
curl -sfL "https://raw.githubusercontent.com/<user>/<repo>/<branch>/<path>"
```
适用：`.c`/`.py`/`.sage`/`.md` 文件。返回就是文件内容，无需转换。

### 方法 2: 博客/文档（HTML → markdown）
```python
# 用 download_sources.py 的 html_to_markdown 函数
# 或手动: curl 下载 → BeautifulSoup 提取正文 → markdownify 转换
from bs4 import BeautifulSoup
from markdownify import markdownify as md

html = curl_download(url)
soup = BeautifulSoup(html, "html.parser")
for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "iframe", "aside"]):
    tag.decompose()
container = soup.find("article") or soup.find("main") or soup.find("div", class_="hfeed") or soup
text = md(str(container), heading_style="ATX")
```
适用：huli/ptr-yudai/PortSwigger/ZKDocs 等博客和文档站点。

### 方法 3: webfetch（备用，适合少量+需 AI 判断价值）
直接用 webfetch 工具获取 markdown 格式内容。适合先快速浏览判断价值，再决定是否下载保存。

### 保存格式
每篇文件头部含 YAML 元信息：
```yaml
---
来源: <URL>
类型: raw / html
获取日期: <YYYY-MM-DD>
---
```
保存到 `download_sources.py` 的 SOURCE_DIR 配置的目录（原始资料区，非 agent 依赖）。

### 下载工具
已有脚本：`$AGENT_DIR/scripts/download_sources.py`
- 无参数：运行硬编码列表
- `--url <URL> --direction <方向> --name <文件名>`：下载单个 URL
- `--github <user/repo> --path <目录> --direction <方向>`：下载 GitHub 仓库目录

---

## §3 价值判断（核心：先判断再下载，避免批量下载低价值内容）

### 判断流程
```
1. 读文章标题/摘要/目录（webfetch 快速浏览，不保存）
2. 问: "知识库中有没有这个技术？"
   - 对照对应方向的 agent 知识库索引表
3. 有 → 跳过（除非文章提供了新角度或更完整的 payload）
4. 没有 → 高价值，下载
```

### 高价值（应该下载）
- **知识库中完全没有的技术**
- **通用原语/决策方法**
- **工具的新用法**
- **完整可执行的 payload/代码**（知识库中只有骨架的）

### 低价值（不下载）
- **具体赛事的 writeup**（技术点与已有知识库重叠）
- **题目级 trick**（一次性，不通用）
- **已有知识库已完整覆盖的技术**

### 教训（本次进化中犯的错误）
| 错误 | 正确做法 |
|------|---------|
| 批量下载一个博客的所有文章 | 先读摘要判断价值，只下载有新技术的 |
| 只下载不提炼 | 下载后必须进入 evolve agent 的 Phase 0 流程 |
| 为了"有源文档"而下载 | 源文档的价值在于"可回溯"，不是"数量多" |
