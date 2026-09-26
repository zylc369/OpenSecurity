# writeup 素材搜索与下载指南

> knowledge-scout（知识侦察 agent）的方法论: 信源注册表（双层）与调用即自进化、扫描方法、gap 判定、价值判断、素材下载、侦察报告格式。不依赖 scout 主提示即可理解。

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
| 信源维护 | staging 变更摘要: 引用收割新发现/末位标记/pending 验证结果，各一行 |
| 遗留 | 发现但本轮未处理的（下轮素材） |

## §1 信源注册表（双层）

**curated 与 staging 的关系**: 不是新旧版本替换关系——curated 是**全量基线**（可信信源完整清单），staging 是**变更队列**（未审核的增量: 新候选/状态更新建议/否决留档）。读取时**合并**，替换只发生在审核转正的单条目 merge。

**文件位置**: curated = `$AGENT_DIR/data/sources-curated.json`; staging = `$AGENT_DIR/data/sources-staging.json`。

**读取规则（合并语义）**:
1. 以 curated 为全量基线
2. staging 中与 curated 同 `domain` 的条目 → 该条目字段覆盖 curated 版本（如更新的 last_seen/refs_in/status 建议）
3. staging 中新 `domain` 的条目 → 作为候选附加（pending，扫描时可顺带验证）
4. staging 文件不存在/空/损坏 → 退化为纯 curated（新 clone 冷启动即此态，流程完整可用）

- **curated（沉淀层）**: 审核转正后的可信基线，随 git 走。
- **staging（工作层）**: 自更新机制的唯一写入目标; 条目多 `proposal` 字段（发现途径+证据+建议动作的自然语言）。也随着 git 走，但是可能被删。
- **写入方式**: bash 写 json 文件——与"下载素材落盘"同源例外（信源状态是侦察产出的运行时数据，不是知识库变更，零写入铁律不破）。

**字段二分法**: 机器判定用固定字段——`domain`（主键）/`tier`（S1 站点级·S2 作者级·O 一次性·AG 聚集体入口）/`status`（curated: active·reduced·archive; staging: pending·rejected——已审否决留档）/`last_seen`（最后有效产出日期）/`refs_in`（被引计数）/`added_at`; 指导行为用自然语言——`profile`（是什么/怎么扫/注意什么）、`proposal`（staging 条目的建议）。写入一律 bash（写工具被白名单禁用），读取用 Read 工具或 bash 均可。

**不在注册表里的来源**: 优先用 webfetch/websearch 搜索，找到后按 §2 方法下载，并在 staging 落 pending 条目。

### CTF Base API 用法（curated 条目 api.ctfbase.com 的操作细节）

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
- category 合法值：取证=`forensics`、Web=`web`、密码学=`crypto`、逆向=`reverse`、Pwn=`pwn`、移动端=`mobile`。AI 安全无对应 category（传 `ai` 报 `Invalid category`），用 websearch 定向检索替代

## §1a 调用即自进化（每次出勤寄生四动作，边际成本≈0）

主任务（扫描/gap 对照/报告）执行的同时：

1. **状态更新**: 每扫描一源，bash 更新 staging 该源 `last_seen` + 产出证据
2. **引用收割**: 读过的 writeup 顺手提取外链（`https?://` 正则），滤噪音后——命中 curated/aggregators 已有源则该源 `refs_in`+1; 新域名追加 staging pending 条目（proposal 写: 引用来源+被引次数）。滤噪音正则: `gyazo|imgur|st-hatena|zenn\.studio|wikipedia|php\.net|mozilla|chrom(e|ium)|googlesource|whatwg|mitre|x\.com|twitter|tiktok|esm\.sh|02\.rs|transfer\.sh|siam\.org|localhost|127\.0\.0\.1|example|attacker\.com|vulnerable|chal\.ctf|flagyard|forms\.gle|ctfcompetition\.com|\.be\.ax|schema\.org|fonts\.|webhook\.site|oastify|ngrok|requestrepo|t\.co|hexo\.io|unpkg|linkedin|medium\.com|<|server`
3. **末位标记**: 本轮接触的源当次计算 §1b 判据，触发则在 staging 该源条目标记建议（降频/移出 + 理由）
4. **pending 顺带验证**: 本轮方向扫描碰到 staging pending 源时顺带核对入表门槛——S1 站点级: 90 天 ≥2 篇机制级产出; S2 作者级: ≥2 个结构化仓库（题目录+分析文档+solve 脚本形态）; AG 聚集体: 能稳定下钻出具体源——达标则在 proposal 升级建议（"建议入表 S1/S2/AG"+ 证据）

**收割脚本**（对已归档目录跑; scout 读未归档单篇时直接用其中的正则+计数逻辑）:

```bash
python3 << 'PYEOF'
import re, glob, collections
DIR = 'docs/资料/writeup-sources/<来源名>'   # ← 改成实际归档目录
domains = collections.Counter()
pat = re.compile(r"https?://([^\s\)\]\>\"'`,]+)")
guide = open('.opencode/knowledge-scout/knowledge-base/knowledge-sourcing-guide.md', encoding='utf-8').read()
noise = re.compile(re.search(r'滤噪音正则: `([^`]+)`', guide).group(1))
for f in glob.glob(DIR + '/**/*.md', recursive=True):
    for u in pat.findall(open(f, encoding='utf-8', errors='ignore').read()):
        d = u.split('/')[0]
        if not noise.search(d): domains[d] += 1
for d, c in domains.most_common(): print(c, d)
PYEOF
```

被引 ≥3 次的域名逐个判读: 已在 curated/aggregators → `refs_in` 累加; 新域名 → staging pending 条目（proposal 写: 引用来源+被引次数+初判）。

staging 写失败（权限/盘满）最多丢本轮增量，主任务不受影响; 文件损坏回退 curated，git 可恢复。

**收割专项**（被 task 派发时的独立形态，不做扫描/gap 对照）: 对指定归档目录跑收割脚本 → count ≥3 的域名逐个判读（是什么源/机制级与否）→ 值得跟踪的写 staging pending（proposal 写证据）→ 噪音丢弃 → 命中已有源的累加 refs_in → 回传摘要（新 pending N 个 / refs_in 累加 M 处）。

## §1b 活力判据（无状态末位淘汰）

判据全部来自源自身携带的信息（文章日期/数量），当次扫描当次计算，**零跨轮次状态依赖**:

| 指标 | 计算 | 判据 |
|---|---|---|
| 近 30 天有效文章数 | 当次扫描统计（有效 = 过 §3 价值判断的） | =0 且最新有效文章 >30 天 → 标记建议降频（status: active→reduced，降频源每季扫一次） |
| 末位排名 | 本轮接触的源按"90 天窗口有效文章数"排名 | 末位且产出 <中位数 1/3 → 标记建议移出（status: →archive，移入冷档案） |

冷档案条目保留（退役日期+原因），复活条件: 被卡壳检索/引用链再次命中 → 拉回 active 重新计数。标记建议只写 staging，经 §1c 审核才变更 curated——一次误判不会真丢源。

## §1c 审核转正（staging → curated，唯一审核关卡）

触发: 用户在 security-analysis-evolve 会话里要求 review 信源，或蒸馏任务前 evolve 顺带执行。流程:

1. 读 staging 全部条目
2. 逐条对照判据 + 抽查可信性（pending 项点开 2-3 篇文章核机制级程度; 标记项核对当次证据）
3. 可信 → merge 进 curated（新增条目 / status 迁移 / refs_in 累加），清 staging 对应条目
4. 不可信 → 删条目，`status: rejected` + 否决理由留档一页（含复活条件）
5. 转正完成后 staging 清空或仅留未决项，`reviewed_at` 更新


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
