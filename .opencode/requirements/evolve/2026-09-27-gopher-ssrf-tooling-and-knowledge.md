# 需求: gopher SSRF 构造工具化 + SSRF/侦察知识增补

> 来源: Groundhog-Day（SunshineCTF 2026）分析复盘。
> 痛点: ① gopher POST 手工构造时 Content-Length 按编码前字符串计算，body 含 `%XX` 时线上字节缩短（libcurl 发送前对 selector 百分号解码）→ 服务端永久等 body → 50 分钟排障; ② wkhtmltopdf 0.12.5 的 XHR file:// 读文件、500 stderr oracle、边界行为未沉淀，靠模型原生知识支撑; ③ CTF 靶机 URL 未知时 33 万次 DNS 字典爆破 0 命中（挑战名非字典词），实际答案在兄弟挑战的 TLS 证书 SAN 里（1 次请求可得全部）。

---

## §1 背景与目标

- **来源**: 2026-09-27 Groundhog-Day 分析复盘（任务目录 `~/bw-security-analysis/workspace/20260927_161743_1319_web-analysis/`，复盘结论: 关键路径 ~75% 靠模型原生知识，外部机制唯一有效纠错是 fresh-eyes）
- **痛点数据**: ① CL 陷阱消耗 ~50 分钟 + 8 次失败实验; ② iframe/data:URI 弯路 ~10 分钟; ③ DNS 爆破负收益 ~10 分钟
- **预期收益**: 同类题（gopher SSRF + PDF 生成器 + CTF 靶机定位）从 ~75 分钟压到 ~10 分钟; CL 错误与伪验证错误结构性杜绝
- **不做什么**: 不改 agent prompt 行为规则（仅函数清单表加一个函数名）; 不动 fresh-eyes 阈值（样本量不足）

## §2 技术方案

### 改动 1: `web-analysis/knowledge-base/ssrf-advanced.md` §4 gopher 节

- line 74 "gopher 协议四坑" 改为 "五坑"，追加第 ⑤ 坑:
  - **机制**: libcurl 发送 gopher selector 前对其做百分号解码——body 中的 `%XX`（3 字符）线上只占 1 字节。手工按编码前字符串计算 Content-Length → CL 虚大 → 服务端按 CL 永久等待 body
  - **症状**: SSRF 目标表现为"挂起"（fetcher 超时、0 字节、无响应头），与请求行/头无关、与 content 无关
  - **防护**: CL 按**解码后**字节数计算（`len(unquote_to_bytes(body))`——与 libcurl percent-decode 对齐，任意 `%XX` 含非 UTF-8 字节按单字节还原; 禁用 str 版 `unquote()`——非 UTF-8 字节替换成 U+FFFD 重编码 3 字节，CL 虚大）; 或 body 避开 `%` 字符（JSON body 经 `json.dumps` 产出不含 `%XX`，天然安全）; 或直接用 `$AGENT_DIR/scripts/web_helpers.py` 的 `build_gopher_url`（自动修正 CL 且对请求行/头 `%` 二次编码，坑结构性消除）
  - **验证同构性规则**: webhook 字节级验证所用 body 必须与实战载荷**字符集同构**——验证 body 不含 `%XX` 而实战含时，"验证通过"不能证明编码路径正确（伪验证）

### 改动 2: `web-analysis/knowledge-base/ssrf-advanced.md` §6 PDF 生成器节

- §6 表格 wkhtmltopdf 行增补: `JS 同步 XHR file://`（比 iframe 稳定）
- 表格后新增一行 wkhtmltopdf 0.12.5 (Qt 4.8.7) 行为细节（payload 一律用行内代码包裹，防 markdown 吞尖括号）:
  - **JS 同步 XHR 读文件完整 payload**: `<script>x=new XMLHttpRequest;x.open("GET","file:///flag.txt",false);x.send();document.write("<pre>"+x.responseText+"</pre>")</script>`
  - **边界**: 目录列举报 `NETWORK_ERR: XMLHttpRequest Exception 101`（仅放行普通文件）; `/proc/*`（cmdline/environ）读出空（size=0 文件）
  - **错误 oracle**: 渲染失败时接口常 500 并回显 wkhtmltopdf stderr（如 `render failed: Exit with code 1 due to network error: ContentNotFoundError`）——可用于文件存在性判定与失败原因定位
  - **iframe 不稳定**: 同 payload 有时 `ContentNotFoundError` 有时静默空白，不作为首选载体
  - **data: URI 子资源有效**: base64 必须完整有效——截断的 base64 报 `ContentNotFoundError`，易误判为"子资源被禁"
  - **原始 body 即文档**: 部分实现把整个请求体写临时文件当主文档渲染（非法 JSON 也渲染）——body 中的 JSON 结构噪音可用 `<style>` 隐藏，或直接发纯 HTML body

### 改动 3: `web-analysis/knowledge-base/web-methodology.md`

- §2.2 line 258 "CTF 单应用效率原则" 行后新增一行:
  - **兄弟子域定位**（目标 URL 未知、但已知同域任一兄弟服务域名时，按序; 初稿名"CTF 靶机定位"，实施时按知识中性原则通用化）: ①`dig +short` 解析已知子域 IP → `echo | openssl s_client -connect <IP>:443 -servername <已知子域> 2>/dev/null | openssl x509 -noout -text | grep -A2 "Subject Alternative Name"`——批量部署的兄弟服务常共用一张多域名证书（同一 LB 后的多站点/多租户均此模式），1 次请求得全部兄弟域名且无 CT 日志入库延迟; ②`crt.sh` 查询（受 CT 日志入库延迟影响，刚部署的证书常查不到）; ③DNS 字典爆破为最后手段——服务命名多为非字典词（拼接词/主题词），命中率极低
- §7.4 line 450 "项目内最小替代路径" 的 crt.sh 处，将 openssl SAN 法标注为优先项（交叉引用 §2.2 新增行）

### 改动 4: `web-analysis/scripts/web_helpers.py` 新增 gopher 构造函数

- 新增公开函数 `build_gopher_url(host: str, port: int, raw_request: str, *, fix_content_length: bool = True) -> str`:
  - 把完整 HTTP 请求文本（请求行+头+body）编码为 gopher selector（`\r`→`%0D`、`\n`→`%0A`、空格→`%20`），返回 `gopher://host:port/_<selector>`
  - `fix_content_length=True`（默认）时: 若请求含 body，按**解码后**字节数（`len(unquote_to_bytes(...))`）重算并回写/补写 `Content-Length` 头（重复的 CL 头去重保留一个）——把 CL 陷阱变成结构上不可能
  - 无 body 时不输出 Content-Length 头
- 新增私有辅助 `_encode_selector(text: str) -> str`（编码规则单一出口）
- 风格与现有函数一致（docstring + 类型注解 + 纯函数）; 零新增依赖（`urllib.parse` 标准库）
- 同步 `agents/web-analysis.md` line 152 函数清单: `web_helpers.py` 行的"主要函数"列追加 `build_gopher_url`

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `web-analysis/knowledge-base/ssrf-advanced.md` | 增补（§4 一行扩展 + §6 一行扩展 + 一行新增） | ~14 行 |
| `web-analysis/knowledge-base/web-methodology.md` | 增补（§2.2 一行新增 + §7.4 一处行内修改） | ~6 行 |
| `web-analysis/scripts/web_helpers.py` | 新增两个函数 | ~85 行 |
| `agents/web-analysis.md` | line 152 行内追加函数名 | ~0（行内） |

### 编码规则

- 知识文本遵守 knowledge-writing-guide: 零来源叙事（不写"本次/实测/复盘中发现"）、一行写完不硬折行、payload 完整可执行、场景驱动三问
- `web_helpers.py` 遵守规则 9（强类型注解; 纯函数属合法例外——无状态单一变换）
- 文档增补用 Edit 精准插入，不动既有行内容（除 line 74 "四坑→五坑" 与 line 450 的行内修改）

### §3.1 实施步骤拆分

步骤 1. ssrf-advanced.md §4 增补 gopher 第五坑
  - 文件: `web-analysis/knowledge-base/ssrf-advanced.md`
  - 预估行数: ~6 行
  - 验证点: `grep -c "五坑" 文件` = 1 且 ⑤ 内容含"百分号解码"与"Content-Length"; 全文无"本次/实测/复盘"叙事词（grep 验证）
  - 依赖: 无

步骤 2. ssrf-advanced.md §6 增补 wkhtmltopdf 0.12.5 细节
  - 文件: `web-analysis/knowledge-base/ssrf-advanced.md`
  - 预估行数: ~8 行
  - 验证点: payload 行可直接复制执行（人工核对引号/标签闭合）; `grep "XMLHttpRequest" 文件` 命中 ≥1
  - 依赖: 无（与步骤 1 同文件不同节，先后执行避免 Edit 冲突）

步骤 3. web-methodology.md 增补兄弟子域定位法（初稿名"CTF 靶机定位"，实施后按知识中性原则改名——该技术对共享 LB 的多租户场景通用）
  - 文件: `web-analysis/knowledge-base/web-methodology.md`
  - 预估行数: ~6 行
  - 验证点: ① §2.2 新行位于 line 258 之后且含完整 openssl 命令（`grep -c "Subject Alternative Name" 文件` = 1，新增行是唯一含全称的行）; ② §7.4 line 450 行内修改后 `grep -c "openssl s_client" 文件` ≥ 1
  - 依赖: 无

步骤 4. web_helpers.py 新增 build_gopher_url
  - 文件: `web-analysis/scripts/web_helpers.py`
  - 预估行数: ~85 行
  - 验证点: ① 语法检查 `python -c "compile(...)"` 通过; ② 功能断言脚本（写在临时目录，不进仓库）: a) 含 `%XX` 的 body（`content=%3Ch1%3Ex%3C%2Fh1%3E`）→ 输出 selector 解码后的 body 为 `content=<h1>x</h1>`（18 字节），URL 中 Content-Length 头值 == 18; b) 无 body 的 GET → 无 Content-Length 头; c) 中文 body → CL 按 UTF-8 字节数（非字符数）; c2) body 含 `#`/`?` → 编码为 %23/%3F（防 fragment 截断/query 语义破坏 selector）; d) `fix_content_length=False` → CL 保持调用方原值不重算; ③ 既有函数不受影响: `import web_helpers` 成功且 5 个既有函数签名不变（inspect 验证）
  - 依赖: 无

步骤 5. agents/web-analysis.md line 152 追加函数名 + 全局终检
  - 文件: `agents/web-analysis.md`
  - 预估行数: 行内 ~15 字符
  - 验证点: ① line 152 含 `build_gopher_url`; ② prompt 展开行数复测 < 450 行（改动为行内追加，不增行; 用 wc + 占位符统计确认）; ③ 终检: 全部改动文件 grep 叙事词（本次|实测|亲测|复盘中|验证过|赛事）零命中; ④ 知识自检清单 7 条逐条回答
  - 依赖: 步骤 4

## §4 验收标准

### 功能验收
1. `build_gopher_url` 对含 `%XX` body 自动产出正确 CL（功能断言脚本全绿）
2. ssrf-advanced.md 五坑齐全，第五坑含机制/症状/防护/验证同构性四要素
3. wkhtmltopdf 增补含完整可复制 payload + 5 项边界行为
4. web-methodology.md 新增定位法含完整 openssl 命令 + 三级优先序
5. web-analysis.md line 152 函数清单含 `build_gopher_url`

### 回归验收
1. `git diff` 确认 ssrf-advanced.md/web-methodology.md 既有行未被改动（除两处声明的行内修改）
2. web_helpers.py 既有 5 函数可正常 import 且签名不变
3. web-analysis.md 展开行数仍 < 450

### 架构验收
1. 无新文件（三个目标文件均为已有文件增补）
2. 归属符合 architecture-map（知识→web-analysis/knowledge-base/、脚本→web-analysis/scripts/、prompt→agents/）
3. 依赖方向不变（web_helpers 仅用标准库 urllib.parse，无反向依赖）

## §5 与现有需求文档的关系

- 独立需求，无前置依赖
- 候选 ④（知识库"动手前先读"指针强化）与 ⑤⑥（fresh-eyes 阈值/固化管道）经用户确认不做，本文档不涉及

## §6 评审与后续修正增补

初版需求实施后，经评审（task `ses_f1ca6a1f5ffe6Sto5QxfWd9QDi`，5 项发现）与用户三轮质询引入的超出 §2 原始范围的行为变化，统一登记:

1. **build_gopher_url 行为扩展**（对应评审项 1/2/4/5）:
   - CL 计算固定用 `unquote_to_bytes`（str 版 `unquote` 对非 UTF-8 字节做 U+FFFD 替换，重编码 3 字节使 CL 虚大）
   - 请求行/头开启 `%` 二次编码（`_encode_selector` 新增 `escape_percent` 参数）——头部"所见即所得"（libcurl 对整个 selector 百分号解码，头部字面 `%XX` 不保护则线上解码变形）; body 保持解码语义，需保留字面 `%XX` 时写 `%25XX`
   - 重复 `Content-Length` 头去重（请求走私特征）
   - 裸 `list` 注解改 `list[str]`
2. **知识条目同步**: ssrf-advanced.md L68 编码基行补充整个 selector 解码契约（头部 %XX 变形与 %25XX 保留法）; L74 公式改 `len(unquote_to_bytes(body))` + 禁用 str 版说明
3. **改名**: §2 改动 3 的"CTF 靶机定位"实施后改为"兄弟子域定位"（知识中性化）
4. **断言集**: 临时脚本扩至 19 项（新增二进制 `%XX` CL 逐字节还原、`%25XX` 保留路径、头部 `%` 保留、重复 CL 去重、新旧公式差异证据）; 期间修掉断言计数器恒不加一的复制粘贴错误（模式 I 实例，已注入自检验证）
5. **制度化**: testing-blind-spot-patterns.md 新增模式 H（不可见字节三联征 + git 考古纪律）与模式 I（自我声称子声称同构性）; evolve prompt 规则 1 `.md` 检查行追加字节扫描
