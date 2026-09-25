# writeup 素材搜索与下载指南

> knowledge-scout（知识侦察 agent）的方法论: 信源选择、扫描方法、gap 判定、价值判断、素材下载、侦察报告格式。不依赖 scout 主提示即可理解。

---

## §0 角色定位与 gap 判定

**侦察非沉淀**: 本流程的产出是侦察报告与落盘素材; 所有知识库写入由 security-analysis-evolve（进化 agent）执行，本流程只产出"建议沉淀清单"。

**gap 两维判定**（逐篇执行，缺一不可）:
- **方向级 gap**: 该技术领域在整个知识库无对应文件——看目录即可判定
- **技术点级 gap**: 已有文件里该技术未覆盖/覆盖不全/不准确——**必须读对应方向知识库的实际内容对照判定，禁止只看文件名索引或 grep 关键词就判"已覆盖"**（关键词命中 ≠ 内容覆盖; 关键词不命中也可能已有等价知识，只是术语不同）

**知识库位置速查**: 通用/逆向 `$SHARED_DIR/knowledge-base/`; 各方向 `<方向>/knowledge-base/`（web-analysis/mobile-analysis/crypto-analysis/ai-security-analysis）。对照时读实际内容，不只看目录名。

## §0a 侦察报告格式

回传给委派方的报告，各节含义:

| 节 | 内容 |
|----|------|
| 扫描范围 | 信源 + 候选篇数 + 时间窗 |
| 跳过清单 | 每篇一行（标题 + 原因: 已覆盖且完整 / 低价值 / 题目级 trick / 无法判期） |
| 建议沉淀清单 | 每条: 技术 + 建议落点（文件 + 小节）+ 价值理由 + 素材路径; 结构性 gap 标注"结构性" |
| 素材路径 | 本次落盘的全部文件位置（供蒸馏直接引用） |
| 遗留 | 发现但本轮未处理的（下轮素材） |

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
| 综合 AI 搜索 | CTF Base | `api.ctfbase.com` | REST API 检索（网页版 `ctfbase.com` 为 JS 渲染，webfetch/curl 只返回 landing page 取不到结果），用法见下方「CTF Base API」 |
| 取证/Web/提权方法论 | HackingArticles | `hackingarticles.in` | curl HTML → BeautifulSoup |
| HTB 渗透/取证 | 0xdf | `0xdf.gitlab.io` | 同上（500+ 机器，详尽度金标准） |

**不在这张表里的来源**：优先用 webfetch 搜索，找到后按 §2 方法下载。

CTF Base API 的 category 合法值：取证=`forensics`、Web=`web`、密码学=`crypto`、逆向=`reverse`、Pwn=`pwn`、移动端=`mobile`。AI 安全无对应 category（传 `ai` 报 `Invalid category`），用 websearch 定向检索替代。

### CTF Base API

```bash
# 搜索：免认证，limit 上限 50
curl -s "https://api.ctfbase.com/api/v1/search?category=web&limit=50&offset=0"
# 全文：仅 is_free=true 的条目免认证返回完整内容
curl -s "https://api.ctfbase.com/api/v1/writeups/<id>/full"
```

search 返回 `results` 数组，每条含 `id`/`title`/`event`/`difficulty`/`description`/`tags`/`techniques`/`is_free`/`content_preview`。关键行为：

- search 返回的 `date` 字段恒为 null；**发布日期编码在 id 前 8 位**（如 `20260829_asisctf2026_2048` = 2026-08-29），时间窗筛选按 id 前缀本地比较
- 结果无排序参数，需 `offset` 递增全量翻页后本地筛；id 无日期前缀的条目无法判期，保守跳过
- `content_preview` 仅 `is_free=true` 的条目有内容；`<id>/full` 返回的 `date` 字段有真实值，取全文后可精确复核日期

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
2. 问: "知识库中有没有这个技术？覆盖得准不准、全不全？"
   - 按 §0 gap 两维判定执行: 不能只看索引表或靠 grep 关键词判定
   - 必须读对应方向知识库的实际内容，确认：有无 / 准确 / 完整
3. 已覆盖且准确完整 → 跳过
4. 没有，或 有但不准/不全/提供了新角度或更完整 payload → 高价值，下载
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

### 常见错误模式
| 错误 | 正确做法 |
|------|---------|
| 批量下载一个博客的所有文章 | 先读摘要判断价值，只下载有新技术的 |
| 只下载不提炼 | 下载是侦察的一半——素材必须进入报告（建议沉淀清单 + 素材路径），由 evolve 决定提炼 |
| 为了"有源文档"而下载 | 源文档的价值在于"可回溯"，不是"数量多" |
