# JS Safe 6.0 — 反调试 + 代码混淆 逆向分析 Writeup

> CTF: Google CTF | 难度: Hard | 题目名: JS Safe 6.0
>
> 题目来源: 本地文件 `js_safe_6.html`
>
> Flag: `CTF{1M_4_C7F_p14y32_4N71_d38U9_721cK5_d0n7_w02K_0n_m3}`

**题目分类：Web 前端安全 + JavaScript 逆向**。本题考察的是 **Chrome DevTools `debug()` API 机制理解** + **tagged template 隐式调用** + **多层编码解码** + **基于 step 计数器的 flag 校验算法** 的组合。

核心思路可以用一句话概括：**题目把 flag 的每个字符藏在经过 ROT13+ROT47 编码的字符池中，用基于 `debug()` condition 的 step 计数器决定取字符的顺序，你需要理解整套机制正向模拟出正确的 flag。**

---

## 目录

- [第一章：你需要先知道的知识](#第一章你需要先知道的知识)
  - [1.1 Chrome DevTools Console 中的 debug() 函数](#11-chrome-devtools-console-中的-debug-函数)
  - [1.2 什么是 debug condition（调试条件）](#12-什么是-debug-condition调试条件)
  - [1.3 什么是 Chrome DevTools Protocol (CDP)](#13-什么是-chrome-devtools-protocol-cdp)
  - [1.4 什么是 includeCommandLineAPI](#14-什么是-includecommandlineapi)
  - [1.5 什么是 Tagged Template（标签模板）](#15-什么是-tagged-template标签模板)
  - [1.6 什么是 ROT13 和 ROT47 编码](#16-什么是-rot13-和-rot47-编码)
  - [1.7 JavaScript 中的 Unicode 隐身字符](#17-javascript-中的-unicode-隐身字符)
  - [1.8 什么是 Proxy 和 Object.defineProperty](#18-什么是-proxy-和-objectdefineproperty)
- [第二章：这道题是什么结构](#第二章这道题是什么结构)
  - [2.1 题目使用说明](#21-题目使用说明)
  - [2.2 整体架构图](#22-整体架构图)
  - [2.3 页面功能：ASCII 旋转立方体](#23-页面功能ascii-旋转立方体)
  - [2.4 三个核心函数：anti()、check()、unlock()](#24-三个核心函数anticheckunlock)
- [第三章：反调试机制深度解析](#第三章反调试机制深度解析)
  - [3.1 机制总览](#31-机制总览)
  - [3.2 机制一：instrument()——debug condition 累加 step](#32-机制一instrument-debug-condition-累加-step)
  - [3.3 机制二：instrumentPrototype()——原型链 getter 劫持](#33-机制二instrumentprototype原型链-getter-劫持)
  - [3.4 机制三：instrumentPrototypeOfPrototype()——Proxy 原型拦截](#34-机制三instrumentprototypeofprototypeproxy-原型拦截)
  - [3.5 机制四：check() 第一行的 Function tagged template](#35-机制四check-第一行的-function-tagged-template)
  - [3.6 机制五：HTML 长度校验](#36-机制五html-长度校验)
  - [3.7 机制六：double() 障眼法](#37-机制六double-障眼法)
  - [3.8 机制七：U+FFA0 隐藏标识符](#38-机制七u+ffa0-隐藏标识符)
  - [3.9 机制八：tagged template 隐式 ROT13](#39-机制八tagged-template-隐式-rot13)
  - [3.10 所有机制如何协同工作](#3a0-所有机制如何协同工作)
- [第四章：破解过程——从失败到成功](#第四章破解过程从失败到成功)
  - [4.1 第一步：静态分析——阅读源码](#41-第一步静态分析阅读源码)
  - [4.2 关键转折点：发现 pool 的 tagged template](#42-关键转折点发现-pool-的-tagged-template)
  - [4.3 最大的错误：误删 ROT13 步骤](#43-最大的错误误删-rot13-步骤)
  - [4.4 失败原因分析：为什么几十个版本全算错了](#44-失败原因分析为什么几十个版本全算错了)
  - [4.5 最终突破：回归正确的 pool 计算](#45-最终突破回归正确的-pool-计算)
  - [4.6 另一个关键教训：不要清除 intervals](#46-另一个关键教训不要清除-intervals)
  - [4.7 机制复盘：每个机制让我走了哪些弯路](#47-机制复盘每个机制让我走了哪些弯路)
- [第五章：完整攻击复现](#第五章完整攻击复现)
  - [5.1 自动化脚本（Python + Playwright）](#51-自动化脚本python--playwright)
  - [5.2 手动验证步骤](#52-手动验证步骤)
- [第六章：如何防御](#第六章如何防御)
- [第七章：总结](#第七章总结)
- [第八章：人类方案 vs AI 方案](#第八章人类方案-vs-ai-方案)
  - [8.1 人类的方案：改 HTML，跑就是了](#81-人类的方案改-html跑就是了)
  - [8.2 AI 的方案：在浏览器里正向计算 flag](#82-ai-的方案在浏览器里正向计算-flag)
  - [8.3 两种方案的对比](#83-两种方案的对比)
  - [8.4 为什么差距这么大](#84-为什么差距这么大)
  - [8.5 如果人类想拿到正确的 flag](#85-如果人类想拿到正确的-flag)

---

## 第一章：你需要先知道的知识

要理解这道题，你需要先了解几个 JavaScript 和 Chrome DevTools 的概念。别担心，我会用最通俗的方式解释每一个。

### 1.1 Chrome DevTools Console 中的 debug() 函数

当你在 Chrome 中按 F12 打开开发者工具（DevTools），切换到 Console（控制台）标签页，你不仅可以在里面执行普通 JavaScript 代码，还能使用一些**只有 Console 才提供的特殊函数**。`debug()` 就是其中之一。

**`debug()` 的作用**：给一个函数设置"条件断点"。当这个函数被调用时，Chrome 会在执行函数体之前，先执行你指定的条件代码。

```javascript
// 语法：debug(目标函数, "条件表达式字符串")
debug(myFunction, "console.log('myFunction 被调用了!'); false");

// 之后每次调用 myFunction()，控制台都会打印消息
myFunction();  // 输出: myFunction 被调用了!
```

关键细节：
- 条件表达式是一个**字符串**，Chrome 会在调用目标函数之前把它当作 JavaScript 执行
- 如果条件表达式返回 `true`（或任何真值），Chrome 会**暂停执行**（触发断点）
- 如果返回 `false`（或任何假值），Chrome **不暂停**，函数正常执行
- 条件表达式中可以执行任意代码，不仅仅是返回 true/false

> **核心要点**：条件表达式中的**所有代码都会被执行**，无论最终返回 true 还是 false。返回值只决定"是否暂停"。本题正是利用了这一点——在条件表达式中执行 `window.step += 源码长度`（累加 step），然后不管返回什么都让程序继续运行。

与之对应的还有 `undebug()`，用来移除断点：

```javascript
undebug(myFunction);  // 移除 myFunction 上的所有 debug 条件
```

**⚠️ 重要**：`debug()` 和 `undebug()` **只存在于 DevTools Console 环境中**。如果你在普通网页的 `<script>` 标签里直接调用 `debug()`，会报 `ReferenceError: debug is not defined`。题目要求你在 Console 中输入 `anti(debug)`，就是利用了这个 Console 专属 API。

### 1.2 什么是 debug condition（调试条件）

上一节说 `debug()` 可以设置条件表达式。这个条件表达式在 Chrome 内部有一个专门的名称：**debug condition**（调试条件）。

理解 debug condition 的关键在于它的**执行时机**和**执行上下文**：

```
调用 myFunction()
  │
  ├── 1. Chrome 检查 myFunction 是否有 debug condition
  │      ↓ 有
  ├── 2. Chrome 执行 debug condition（条件表达式）
  │      ↓
  ├── 3. 如果条件返回 true → 暂停执行（断点触发）
  │      如果条件返回 false → 不暂停，继续
  │      ↓
  └── 4. 执行 myFunction 的函数体
```

**关键特性**：当 Chrome 在执行一个 debug condition 时，如果这个 condition 内部又调用了其他被 `debug()` 标记的函数，Chrome **默认会抑制这些嵌套的 condition 评估**，直接执行被调用函数的函数体。这是为了防止无限嵌套（A 的 condition 调用 B → 触发 B 的 condition → B 的 condition 调用 C → 触发 C 的 condition → ...永无止境）。这个特性意味着 step 的增量在不同调用上下文中差异巨大——嵌套调用时 step 增长较少，直接调用时 step 增长极多。这也是为什么在 Python 中手动模拟 step 增量几乎不可能算对（详见 [4.7 机制复盘](#47-机制复盘每个机制让我走了哪些弯路)）。

### 1.3 什么是 Chrome DevTools Protocol (CDP)

**Chrome DevTools Protocol（CDP）** 是 Chrome 浏览器提供的一套远程控制协议。它允许外部程序通过网络连接来控制 Chrome——就像你手动操作 DevTools 一样，但全部自动化。

用类比来理解：如果 DevTools 界面是你手动操作 Chrome的"方向盘"，那 CDP 就是"自动驾驶 API"——你可以用代码来做同样的事情。

本题中，我们用 **Playwright**（一个浏览器自动化库）通过 CDP 来：
- 打开 Chrome 浏览器
- 导航到指定页面
- 在页面的 JavaScript 环境中执行代码（相当于在 Console 中输入）
- 捕获 alert 弹框

CDP 中执行 JavaScript 的命令是 `Runtime.evaluate`：

```python
# 通过 CDP 在 Chrome 中执行 JavaScript
cdp_session.send("Runtime.evaluate", {
    "expression": "1 + 2",           # 要执行的 JS 代码
    "returnByValue": True,            # 返回值而不是引用，下面有解释
    "includeCommandLineAPI": True,    # 关键！见下一节
})
# 返回: {"result": {"value": 3}}
```

**`returnByValue` 是什么意思？**

在 CDP 中，JavaScript 表达式的结果有两种返回方式：

| 参数 | 行为 | 返回内容 |
|------|------|---------|
| `returnByValue: False`（默认） | 返回引用 | `{"type": "object", "objectId": "12345.abc"}` |
| `returnByValue: True` | 返回值 | `{"type": "number", "value": 3}` |

用类比来理解：

```
returnByValue: False（引用模式）
  你问 Chrome: "1+2 等于多少？"
  Chrome 回答: "结果在第三个抽屉里，自己去拿" → objectId（远程对象的句柄）
  → 要看实际内容，还需要再发一次 CDP 请求：
     cdp_session.send("Runtime.getProperties", {"objectId": "12345.abc"})

returnByValue: True（值模式）
  你问 Chrome: "1+2 等于多少？"
  Chrome 回答: "3" → 直接序列化为 JSON 返回实际值
```

举个例子，对一个对象：

```python
# 引用模式（默认）
result = cdp_session.send("Runtime.evaluate", {
    "expression": "({name: 'Alice', age: 30})",
    "returnByValue": False,
})
# 返回: {"result": {"type": "object", "objectId": "12345.abc"}}
# 你只拿到一个 ID，看不到 name 和 age

# 值模式
result = cdp_session.send("Runtime.evaluate", {
    "expression": "({name: 'Alice', age: 30})",
    "returnByValue": True,
})
# 返回: {"result": {"type": "object", "value": {"name": "Alice", "age": 30}}}
# 直接拿到完整数据
```

**什么时候用哪个？**

| 场景 | 选择 | 原因 |
|------|------|------|
| 简单值（数字、字符串、布尔） | `True` | 直接拿到值，方便 |
| 需要检查对象属性 | `True` | 大多数情况够用 |
| 对象很大/嵌套很深 | `False` | 避免序列化开销 |
| 需要继续操作这个对象 | `False` | 保留引用，可以后续调用方法 |

本题中我们全部用 `returnByValue: True`，因为我们只需要简单的结果（step 值、success 布尔值）。

### 1.4 什么是 includeCommandLineAPI

这是本题自动化验证的关键参数，也是很多读者会困惑的地方。

还记得前面说 `debug()` 函数**只存在于 Console 环境中**吗？当你通过 CDP 的 `Runtime.evaluate` 执行代码时，默认情况下它是**普通 JavaScript 执行环境**，不包含 `debug()` 等 Console 专属函数。

`includeCommandLineAPI: true` 的作用就是告诉 Chrome：**"请在 Console API 环境中执行这段代码"**，使得 `debug()`、`undebug()`、`$()` 等函数可用。

```python
# ❌ 没有 includeCommandLineAPI → debug 未定义
cdp.send("Runtime.evaluate", {
    "expression": "debug(check, 'false')",
    "returnByValue": True,
})
# 报错: ReferenceError: debug is not defined

# ✅ 有 includeCommandLineAPI → 正常执行
cdp.send("Runtime.evaluate", {
    "expression": "debug(check, 'false')",
    "returnByValue": True,
    "includeCommandLineAPI": True,  # 关键！
})
# 成功
```

**Console Utilities API（命令行工具 API）完整列表**

这些函数只存在于 DevTools Console 环境中，在网页的普通 `<script>` 标签或 Node.js 中都不存在：

| 函数 | 作用 |
|------|------|
| `$(selector)` | 等价于 `document.querySelector()` |
| `$$(selector)` | 等价于 `document.querySelectorAll()` |
| `$0` | 当前在 Elements 面板中选中的元素 |
| **`debug(fn)`** | **给函数设置断点（函数被调用时暂停）← 本题核心** |
| **`undebug(fn)`** | **取消断点** |
| `monitor(fn)` | 监控函数调用（Console 中打印调用信息） |
| `unmonitor(fn)` | 取消监控 |
| `copy(object)` | 复制对象到剪贴板 |
| `clear()` | 清空 Console |
| `keys(object)` | 返回对象的所有键名 |
| `values(object)` | 返回对象的所有值 |
| `table(data)` | 以表格形式展示数据 |

```javascript
// ✅ 在 DevTools Console 中直接输入 → 正常工作
debug(myFunction);

// ❌ 在网页的 <script> 标签中 → 报错
// ReferenceError: debug is not defined
```

**这和我们手动在 DevTools Console 里输入命令有什么区别？**

从 JavaScript 执行的角度看，**几乎没有区别**。`Runtime.evaluate` + `includeCommandLineAPI` 就是让 CDP 在和 Console 相同的环境中执行代码。

有一个区别是：通过 CDP 执行的命令**不会出现在 Console 的历史记录中**——所以你用 CDP 执行了代码，在 DevTools Console 面板里看不到输入过的命令。但代码的执行效果（变量修改、函数调用等）是完全一样的。

### 1.5 什么是 Tagged Template（标签模板）

这是 ES6 引入的一个 JavaScript 特性，也是本题最精妙的trick之一。

普通的模板字符串用反引号包裹：

```javascript
const name = "Alice";
const greeting = `Hello, ${name}!`;  // "Hello, Alice!"
```

**Tagged template** 在模板字符串前面加一个函数名（称为"标签函数"）：

```javascript
function myTag(strings, ...values) {
    // strings: ${} 之间的静态文本部分（数组）
    // values: ${} 中表达式的求值结果（剩余参数）
    return strings[0] + values[0] + strings[1];
}

const name = "Alice";
const result = myTag`Hello, ${name}!`;  // "Hello, Alice!"
//                   ^^^^^   ^^^^^
//                  strings[0]  values[0]="Alice"
//                              strings[1]="!"
```

当模板字符串中没有 `${}` 时，标签函数只收到 `strings` 数组（`values` 为空）：

```javascript
function shout(parts) {
    return parts[0].toUpperCase();
}

shout`hello`;  // "HELLO"
// parts = ["hello"]，没有 values
```

**本题中的应用**：题目定义了一个变量，变量名是 `ﾠ`（U+FFA0，一个不可见字符），这个变量的值是一个**做 ROT13 变换的函数**。然后把它当作 tagged template 的标签函数，对 pool 字符串进行隐式变换：

```javascript
// 1. 题目先定义了一个函数，变量名是不可见字符
let ﾠ = function(s) { /* 做 ROT13 变换 */ };

// 2. 然后用不可见变量名作为标签函数
let pool = ﾠ`?o>...\`5`;
//        ↑ 这个不可见字符实际上是一个函数名
//        tagged template 会自动调用这个函数

// 等价于：
let pool = rot13("?o>...`5")
```

这个 trick 非常隐蔽，有两层伪装：
- **第一层**：变量名 `ﾠ`（U+FFA0）在编辑器中几乎不可见，阅读代码时很难注意到这里有一个标签函数
- **第二层**：tagged template 语法让函数调用看起来像普通的字符串赋值

### 1.6 什么是 ROT13 和 ROT47 编码

**ROT13**（Rotate by 13 places）：把英文字母循环移动 13 位。a→n, b→o, ..., n→a, o→b。只变换字母，其他字符不变。ROT13 是自逆的：对结果再做一次 ROT13 就还原了。

```
ROT13("Hello") = "Uryyb"
ROT13("Uryyb") = "Hello"
```

**ROT47**：比 ROT13 更通用的版本，作用于 ASCII 可见字符范围（33-126，共 94 个字符）。每个字符的 ASCII 码移动 47 位。和 ROT13 一样，ROT47 也是自逆的：对结果再做一次 ROT47 就还原了（47 × 2 = 94，刚好一圈）。

```
ROT47("Hello") = "w*44>"
ROT47("w*44>") = "Hello"
```

本题中 pool 字符串经过 **ROT13 → ROT47** 两层变换，解码后得到真正的字符池。详细的解码过程见 [3.9 机制八：tagged template 隐式 ROT13](#39-机制八tagged-template-隐式-rot13)。

### 1.7 JavaScript 中的 Unicode 隐身字符

JavaScript 允许在标识符（变量名、函数名）中使用 Unicode 字符。题目利用了一个特殊字符 **U+FFA0**（HALFWIDTH HANGUL FILLER，半角韩文填充符）。

这个字符的狡猾之处在于：
- 它在大多数编辑器中**看起来像一个空格**
- 但它是一个**合法的 JavaScript 标识符字符**
- 所以 `window.step` 和 `window.stepﾠ`（后面有 U+FFA0）是**两个完全不同的变量**

```javascript
window.step = 100;          // 普通 step 变量
window.stepﾠ = 5;           // step + U+FFA0，另一个完全不同的变量！

console.log(window.step);    // 100
console.log(window.stepﾠ);   // 5
```

在本题中，`double()` 函数看似会修改 `window.step`（翻倍），实际上修改的是 `window.stepﾠ`——一个完全无关的变量。这就是一个障眼法。（`window.step` 是题目的核心计数器，详见 [2.4 三个核心函数](#24-三个核心函数anti-check-unlock) 和 [3.2 机制一](#32-机制一instrument-debug-condition-累加-step)）

### 1.8 什么是 Proxy 和 Object.defineProperty

这两个是 JavaScript 的高级特性，题目用它们来实现"每次调用数组方法都计数"的效果。

**Object.defineProperty** 可以在对象上定义新属性或修改现有属性。第三个参数叫**属性描述符（descriptor）**，分为两种类型：

| 类型 | 特有字段 | 本质 |
|------|---------|------|
| **数据描述符** | `value`、`writable` | 直接存一个值（任何类型） |
| **访问器描述符** | `get`、`set` | 访问时调函数、赋值时调函数 |

两种类型还共享三个字段：

| 共有字段 | 含义 | `true` 时 | `false` 时 |
|---------|------|----------|-----------|
| `enumerable`（可枚举） | 属性是否出现在遍历中 | `Object.keys(obj)` 能看到 | 属性存在但遍历看不到 |
| `configurable`（可配置） | 描述符能否再修改 | 可以修改描述符、删除属性 | 锁死，不能改不能删 |
| `writable`（可写） | 值能否修改（仅数据描述符） | `obj.name = "x"` 成功 | 赋值静默失败 |

一个完整的描述符示例：

```javascript
Object.getOwnPropertyDescriptors(Array);
// {
//     length:    { value: 1, writable: false, enumerable: false, configurable: false },
//     name:      { value: "Array", writable: false, enumerable: false, configurable: false },
//     prototype: { value: Array.prototype, writable: false, enumerable: false, configurable: false },
//     isArray:   { value: ƒ isArray(), writable: true, enumerable: true, configurable: true },
//     from:      { value: ƒ from(), writable: true, enumerable: true, configurable: true },
//     of:        { value: ƒ of(), writable: true, enumerable: true, configurable: true },
// }
```

用 `Object.defineProperty` 设置属性的示例：

```javascript
Object.defineProperty(obj, "age", {
    value: 30,       // 存的值
    writable: true,  // 可以修改
});
console.log(obj.age);  // 30，直接返回存的值

// 访问器描述符——访问时执行函数
Object.defineProperty(obj, "name", {
    get: () => { console.log("name 被访问了!"); return "Alice"; }
});

console.log(obj.name);  // 先打印 "name 被访问了!"，然后打印 "Alice"
//                    ↑ 看起来像访问普通值，实际上调用了 get 函数
```

**关键点**：从使用方式上无法区分一个属性是数据描述符还是访问器描述符——`obj.name` 在两种情况下写法完全一样。题目正是利用这一点，偷偷把数组方法替换成了带 `step++` 的访问器（详见 [3.3 机制二](#33-机制二instrumentprototype原型链-getter-劫持) 和 [3.4 机制三](#34-机制三instrumentprototypeofprototypeproxy-原型拦截)）。

**Proxy** 可以拦截对象的所有操作：

```javascript
const handler = {
    get(target, prop) {
        console.log(`访问了属性: ${prop}`);
        return target[prop];
    }
};

const arr = new Proxy([1, 2, 3], handler);
arr.length;  // 打印 "访问了属性: length"
arr[0];      // 打印 "访问了属性: 0"
```

在本题中：
- `instrumentPrototype()` 用 `Object.defineProperty` 给 `Array.prototype` 上的方法（shift、splice 等）设置了 getter，每次访问这些方法时 `step++`
- `instrumentPrototypeOfPrototype()` 用 `Proxy` 包裹了 `Array.prototype` 的原型，拦截所有属性查找，每次也 `step++`（详见 [3.4 机制三](#34-机制三instrumentprototypeofprototypeproxy-原型拦截)）

这两个机制共同构成了 step 计数器的一部分——即使没有 debug condition，这些 getter 和 proxy 也会在每次操作时增加 step。

### 1.9 什么是 Debugger.enable 和自动 resume

Chrome 的调试器默认是关闭的。通过 CDP 发送 `Debugger.enable` 命令，Chrome 会打开调试器，让它能处理断点和 debug condition。CDP 只是"指令手册"，真正执行命令的是 Chrome。

**正常流程中，debug condition 不会触发暂停**。前面分析过：
- 第一个 debug condition（累加 step）返回 `undefined`（falsy）→ 不暂停
- 第二个 debug condition（HTML 长度校验）返回 `false`（falsy）→ 不暂停
- check() 第一行的 `Function\`...\`` 只创建函数从不调用，函数体中的 `while(true) debugger` 永远不会执行 → 不暂停

所以你在 DevTools 中手动操作时，全程不会有断点暂停。

那为什么自动化脚本中还要加 `Debugger.enable` + 自动 resume？因为**调试器需要先启用，debug condition 才会执行**。如果不发 `Debugger.enable`，Chrome 会完全忽略 debug condition——条件表达式里的 `window.step += l` 不会执行，step 就不会累加，flag 就算不对。自动 resume 只是防御性措施，防止意外情况下程序卡死。

```python
# 启用调试器（必须，否则 debug condition 不执行）
cdp.send("Debugger.enable", {})

# 防御性措施：万一触发了断点，自动继续
def on_paused(params):
    cdp.send("Debugger.resume", {})

cdp.on("Debugger.paused", on_paused)
```

**这不影响 flag 的计算**。因为 flag 的正确性取决于 step 计数器的值，而 step 是在 debug condition 的条件表达式执行过程中累加的——无论 Chrome 是否暂停过，条件表达式的执行结果都一样。`resume` 只是告诉 Chrome"我看到了，继续执行"，类似于你在 DevTools 里点了"继续"按钮。

---

## 第二章：这道题是什么结构

这一章我们从宏观角度看整个题目的运作流程，理解数据如何在各函数之间流转。

### 2.1 题目使用说明

题目给出了明确的使用步骤：

```
1. 用 Chrome 打开页面
2. 按 F12 打开 DevTools
3. 在 Console 中输入: anti(debug);       // 初始化反调试系统
4. 在 Console 中输入: unlock("密码");    // 尝试解锁 → 弹出 alert 显示密文内容
5. 可选: store("新密文");                // 存储新的加密内容
```

我们的目标是找到正确的"密码"，使得 `unlock("密码")` 触发 alert 弹框。

### 2.2 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     js_safe_6.html 页面                          │
│                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐                    │
│  │  渲染动画脚本      │    │  安全逻辑脚本      │                    │
│  │  renderFrame()    │    │  anti()           │                    │
│  │  setInterval      │    │  check()          │                    │
│  │  3D旋转立方体      │    │  unlock()         │                    │
│  │                   │    │  store()          │                    │
│  └──────────────────┘    └──────────────────┘                    │
│           │                       │                               │
│           │              ┌────────┴────────┐                     │
│           │              │  instrument()    │                     │
│           │              │  instrumentPrototype()                │
│           │              │  instrumentPrototypeOfPrototype()     │
│           │              └─────────────────┘                     │
│           │                       │                               │
│           └─────── 共同驱动 ───────┘                               │
│                       window.step 计数器                          │
│                                                                  │
│  localStorage: { content: [加密后的密文数组] }                      │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 页面功能：ASCII 旋转立方体

页面的外观是一个 ASCII 字符构成的 3D 旋转立方体动画，由 `renderFrame()` 函数每帧渲染。这个动画不是装饰——它被题目"征用"为 step 计数器的一部分：

- `renderFrame()` 在每帧中调用大量数组方法（map、forEach、join 等）和数学函数（sin、cos 等）
- 这些方法都被 `instrument()` 加了 debug condition
- 所以每次 `renderFrame()` 执行，`window.step` 都会增加一大截

在 check() 的 while 循环中，每次匹配一个字符后都调用 `renderFrame()`，用它来推进 step 计数器。

### 2.4 三个核心函数：anti()、check()、unlock()

#### anti(debug) —— 初始化

```javascript
function anti(debug) {
    // debug 参数：Chrome Console 的 debug 函数，anti 内部没有直接使用
    // 传入它只是为了让题目描述 "anti(debug)" 看起来像"执行反调试初始化"
    
    window.step = 0;           // 步数计数器清零
    window.cﾠ = true;          // 启用 debug condition 计数（c 后面有 U+FFA0）
    window.success = false;    // 解锁状态：未解锁
    
    window.r = function(s) { /* ROT47 */ };   // ROT47 解码函数，变量名是 r
    window.ﾠ = function(s) { /* ROT13 */ };   // ROT13 解码函数，变量名是 U+FFA0（不可见字符）
    // 注：源码中 window.k 只是注释，实际赋值的变量名是 ﾠ（第 249 行）
    
    window.check = function() { /* 密码校验 */ };
    
    // 对所有关键函数加上 debug condition（累加 step + 篡改检测）
    // 完整代码：
    [Array, Array.prototype, String.prototype, Math, console, Reflect].map(o =>
        Object.values(Object.getOwnPropertyDescriptors(o))  // 获取每个对象上所有属性的描述符
        .map(x => x.value || x.get)                          // 提取属性值（普通值或 getter）
        .filter(x => x instanceof Function)                  // 只保留函数
    ).flat()              // 把 6 个数组合并成一个大数组（二维→一维）
    .concat(check, eval)  // 再追加 check 和 eval 两个函数
    .forEach(instrument);  // 对每个函数调用 instrument() 插桩
    
    instrumentPrototype(Array.prototype);            // 数组方法 getter 劫持
    instrumentPrototypeOfPrototype(Array.prototype);  // Proxy 拦截
}
```

> **详情导航**：
> - `window.step`（步数计数器）→ 见 [3.2 机制一](#32-机制一instrument-debug-condition-累加-step)
> - `window.cﾠ`（U+FFA0 隐藏标识符）→ 见 [3.8 机制七：U+FFA0 隐藏标识符](#38-机制七u+ffa0-隐藏标识符)
> - `window.r`（ROT47 解码函数）→ 见 [1.6 什么是 ROT13 和 ROT47 编码](#16-什么是-rot13-和-rot47-编码)
> - `window.ﾠ`（ROT13 解码函数，变量名是 U+FFA0）→ 见 [3.8 机制七：U+FFA0 隐藏标识符](#38-机制七u+ffa0-隐藏标识符) 和 [3.9 机制八：tagged template 隐式 ROT13](#39-机制八tagged-template-隐式-rot13)
> - `instrument()`（给函数加 debug condition）→ 见 [3.2 机制一](#32-机制一instrument-debug-condition-累加-step)
> - `instrumentPrototype()`（数组方法 getter 劫持）→ 见 [3.3 机制二：instrumentPrototype()——原型链 getter 劫持](#33-机制二instrumentprototype原型链-getter-劫持)
> - `instrumentPrototypeOfPrototype()`（Proxy 原型拦截）→ 见 [3.4 机制三：instrumentPrototypeOfPrototype()——Proxy 原型拦截](#34-机制三instrumentprototypeofprototypeproxy-原型拦截)

##### 提取函数的链式调用详解

上面代码中最复杂的部分是这段链式调用：

```javascript
[Array, Array.prototype, String.prototype, Math, console, Reflect].map(o =>
    Object.values(Object.getOwnPropertyDescriptors(o))
    .map(x => x.value || x.get)
    .filter(x => x instanceof Function)
).flat().concat(check, eval).forEach(instrument);
```

逐步拆解。

**`Array` 和 `Array.prototype` 的区别**：

- `Array` 是构造函数本身。它身上挂的是**静态方法**：`Array.isArray()`、`Array.from()`、`Array.of()` 等。不需要创建数组就能用
- `Array.prototype` 是所有数组实例共享的原型对象。它身上挂的是**实例方法**：`push`、`splice`、`map`、`join` 等。所有数组都能用

```javascript
Array.isArray([1,2,3]);  // true，静态方法，直接从 Array 上取
[1,2,3].push(4);         // 实例方法，从 Array.prototype 上继承
```

题目需要给两种方法都加 debug condition，所以 `Array` 和 `Array.prototype` 都出现在列表中。`String.prototype`、`Math`、`console`、`Reflect` 同理——它们身上各有各的方法，都需要插桩。

**第1步：`Object.getOwnPropertyDescriptors(o)`** — 获取对象上所有自身属性的完整描述符

每个属性都有一个描述符，描述符有两种类型（见 [1.8 什么是 Proxy 和 Object.defineProperty](#18-什么是-proxy-和-objectdefineproperty)）：

```javascript
// 以 Array 为例：
Object.getOwnPropertyDescriptors(Array);
// {
//     length:    { value: 1, writable: false, enumerable: false, configurable: false },
//     name:      { value: "Array", writable: false, enumerable: false, configurable: false },
//     prototype: { value: Array.prototype, writable: false, enumerable: false, configurable: false },
//     isArray:   { value: ƒ isArray(), writable: true, enumerable: true, configurable: true },
//     from:      { value: ƒ from(), writable: true, enumerable: true, configurable: true },
//     of:        { value: ƒ of(), writable: true, enumerable: true, configurable: true },
// }
```

描述符中的两个字段说明：
- **enumerable**（可枚举的）：为 `true` 时，属性会出现在 `Object.keys()`、`for...in` 等遍历中。为 `false` 时，属性存在但遍历看不到
- **configurable**（可配置的）：为 `true` 时，属性的描述符可以再修改或删除属性。为 `false` 时，属性被锁死

**第2步：`Object.values(...)`** — 提取对象中所有属性的值，返回数组

`Object.values` 不关心值是什么类型，它只做一件事：把对象里所有属性的值取出来变成数组。

```javascript
const obj = { a: 1, b: "hello", c: [1,2] };
Object.values(obj);  // [1, "hello", [1,2]]
```

在这里，值恰好是描述符对象：

```javascript
Object.values(Object.getOwnPropertyDescriptors(Array));
// [
//     { value: 1, writable: false, ... },               // length 的描述符
//     { value: "Array", writable: false, ... },          // name 的描述符
//     { value: Array.prototype, writable: false, ... },  // prototype 的描述符
//     { value: ƒ isArray(), writable: true, ... },       // isArray 的描述符
//     { value: ƒ from(), writable: true, ... },          // from 的描述符
//     { value: ƒ of(), writable: true, ... },            // of 的描述符
// ]
```

**第3步：`.map(x => x.value || x.get)`** — 从描述符中取出实际的值

- 数据描述符有 `value` 字段 → 取 `x.value`（函数就是 `ƒ push()`，非函数就是数字、字符串等）
- 访问器描述符没有 `value`，有 `get` 字段 → `x.value` 是 `undefined`，取 `x.get`（getter 函数）
- 如果一个属性只有 `set` 没有 `get` → `x.value` 和 `x.get` 都是 `undefined` → 丢失（但本题不关心这种情况）

```javascript
// Array 经过这步后：
[1, "Array", Array.prototype, ƒ isArray(), ƒ from(), ƒ of()]
```

**第4步：`.filter(x => x instanceof Function)`** — 只保留函数类型

数字、字符串、对象等全部丢掉，只留函数：

```javascript
// Array 经过这步后：
[ƒ isArray(), ƒ from(), ƒ of()]
```

**第5步：`.flat()`** — 把 6 个数组合并成一个大数组

前面 `.map()` 对 6 个对象（Array、Array.prototype、String.prototype、Math、console、Reflect）各生成一个函数数组，结果是一个二维数组（数组的数组）。`.flat()` 把它压平成一维数组。

```javascript
// 之前（二维）：
[[ƒ isArray(), ƒ from(), ƒ of()], [ƒ push(), ƒ splice(), ƒ map(), ...], [ƒ split(), ...], ...]
// 之后（一维）：
[ƒ isArray(), ƒ from(), ƒ of(), ƒ push(), ƒ splice(), ƒ map(), ..., ƒ split(), ...]
```

**第6步：`.concat(check, eval)`** — 追加两个不在列表中的函数

`check` 和 `eval` 不在前面 6 个对象中，需要单独加上。`concat` 把两个元素追加到数组末尾。

**第7步：`.forEach(instrument)`** — 对每个函数调用 `instrument()` 插桩

等价于：

```javascript
instrument(ƒ isArray());
instrument(ƒ from());
instrument(ƒ push());
instrument(ƒ splice());
// ... 所有函数都加一遍
```

`anti()` 做了三件事：
1. 定义工具函数（r = ROT47, ﾠ = ROT13）和校验函数（check）
2. 给大量函数加 debug condition（通过 `instrument()`，详见 [3.2 机制一](#32-机制一instrument-debug-condition-累加-step)）
3. 修改 `Array.prototype` 的属性描述符和原型链（通过 `instrumentPrototype` 详见 [3.3 机制二](#33-机制二instrumentprototype原型链-getter-劫持) 和 `instrumentPrototypeOfPrototype` 详见 [3.4 机制三](#34-机制三instrumentprototypeofprototypeproxy-原型拦截)）

#### check() —— 密码校验

这是最核心的函数。简化后的逻辑：

```javascript
function check() {
    // Function tagged template —— 只创建函数不调用，函数体中的自检代码从未执行
    // 真正作用：调用 Function 触发 debug condition，累加 step（障眼法，详见 3.5 节）
    
    try {
        window.step = 0;        // 重置计数器
        [0].step;               // 触发一次 Proxy → step=1
        
        const flag = (window.flag || '').split('');  // 待验证的 flag
        let i = 1337, j = 0;
        
        // ⚠️ 关键：pool 是 tagged template，U+FFA0(ROT13) 是标签函数！
        let pool = ROT13`?o>...\`5`;  // 先 ROT13
        pool = r(pool).split('');       // 再 ROT47，得到真正的字符池
        
        const double = Function.call`window.step[U+FFA0] *= 2`;  // 障眼法：Function.call + tagged template 创建的是空函数体，double() 什么都不做
        
        while (!window.success) {
            // 用 step 计数器和伪随机数决定取 pool 中的哪个字符
            j = ((i || 1) * 16807 + window.step) % 2147483647;
            
            if (flag[0] == pool[j % pool.length] && window.step < 1000000) {
                // 匹配成功！移除已匹配的字符
                i = j;
                flag.shift();           // 移除 flag 第一个字符 → step++
                pool.splice(j % pool.length, 1);  // 移除 pool 中对应字符 → step++
                renderFrame();           // 渲染一帧 → step 大幅增加
                double();                // 空函数，什么都不做（详见 3.7 机制六）
                
                if (!pool.length && !flag.length) window.success = true;
            }
            // 不匹配 → 死循环（因为 success 永远不会变 true）
        }
    } catch(e) {}  // 静默吞掉所有错误
}
```

核心算法：
1. **pool** 是经过 ROT13+ROT47 解码后的 49 个字符
2. 用线性同余生成器（`j = (i * 16807 + step) % 2147483647`）产生伪随机数
3. `j % pool.length` 决定要检查 pool 中的哪个字符
4. 如果 flag 的当前第一个字符与 pool[j%len] 匹配，就从两者中都移除，并推进 step
5. 49 个字符全部匹配 → `success = true`
6. 如果 step 超过 1000000 还没匹配完 → 条件失败，死循环

#### unlock(flag) —— 解锁入口

```javascript
function unlock(flag) {
    // 1. 正则验证 flag 格式：必须是 CTF{字母数字下划线@!?-}
    const match = /^CTF{([0-9a-zA-Z_@!?-]+)}$/.exec(flag);
    if (!match) return false;
    
    // 2. 提取花括号内的密码（去掉 CTF{ 和 }）
    // 例如 "CTF{abc123}" → match[1] = "abc123"
    window.flag = match[1];
    
    // 3. 调用 check() 验证密码是否正确
    check();
    
    // 4. 如果验证通过，用密码解密 localStorage 中存储的密文
    if (!window.success) return;
    
    // 把密码字符串转成 ASCII 码数组
    // 例如 "abc123" → [97, 98, 99, 49, 50, 51]
    window.password = Array.from(window.flag).map(c => c.charCodeAt());
    
    // 从 localStorage 取出密文（数字数组）
    const encrypted = JSON.parse(localStorage.content || '[]');
    
    // 用 XOR 解密：密文的每个数字和密码的对应数字做异或运算
    // 密码不够长就循环使用（i % password.length）
    // 例如 encrypted[0] ^ password[0], encrypted[1] ^ password[1], ...
    const decrypted = encrypted.map((c, i) => c ^ password[i % password.length])
                               .map(String.fromCharCode).join('');
    alert("JS Safe opened! Content:" + decrypted);
}
```

**flag 和密码的关系**：`unlock("CTF{密码}")` 做了两件事——先用 `check()` 检查密码是否正确，如果正确就用这个密码通过 XOR 解密 localStorage 里存储的密文，然后弹窗显示解密结果。

注意正则表达式 `/^CTF{([0-9a-zA-Z_@!?-]+)}$/`：flag 只能包含字母、数字、下划线、`@`、`!`、`?`、`-`。这意味着 pool 解码后的所有字符都必须在这个范围内——这是验证 pool 计算是否正确的重要线索。

---

## 第三章：反调试机制深度解析

这一章我们逐个拆解题目的 8 个反调试/混淆机制，理解它们各自做什么、如何工作、以及它们如何协同构成 step 计数器。

> **核心发现**：这些"反调试机制"并不是要被"绕过"的障碍——它们是 step 计数器的**组成部分**，是 flag 校验算法的核心。正确理解并让它们正常运行，才能得到正确的 flag。

### 3.1 机制总览

| # | 机制 | 作用 | 对 step 的影响 |
|---|------|------|---------------|
| 1 | instrument() | 给函数加 debug condition（累加 step） | 每次调用被 instrument 的函数，step += 函数源码长度 |
| 2 | instrumentPrototype() | 劫持 Array.prototype 方法为 getter | 每次访问数组方法（shift、splice等），step += 1 |
| 3 | instrumentPrototypeOfPrototype() | Proxy 拦截 Array 原型链 | 每次属性查找经过 Proxy，step += 1 |
| 4 | Function tagged template | check() 第一行调用 Function 创建函数 → 触发 debug condition 累加 step。函数体里的自检代码（`while(true) debugger`）是障眼法，从未执行 | 调用 Function 时 step += Function 源码长度（本质是机制 1 的一个触发点） |
| 5 | HTML 长度校验 | 检测 HTML 是否被修改 → 断点暂停 | 无（防篡改，不影响 step） |
| 6 | double() 障眼法 | 看似翻倍 step，实际是 no-op | 无（障眼法） |
| 7 | U+FFA0 隐藏标识符 | 用不可见字符隐藏关键变量名 | 无（代码混淆） |
| 8 | tagged template ROT13 | 用标签模板隐式调用 ROT13 | 无（pool 编码） |

**如何理解这张表？**

这 8 个机制分为三类角色：

| 角色 | 机制 | 说明 |
|------|------|------|
| **干活的主力** | 1、2、3 | 直接累加 `window.step`，是 flag 校验算法的核心组成部分。机制 4 本质上也是机制 1 的一个触发点（调用 Function 触发 debug condition），不是独立的 step 来源 |
| **看门护院的保镖** | 5 | 检测 HTML 是否被修改，阻止你篡改代码 |
| **障眼法和暗门** | 4（自检部分）、6、7、8 | 不参与 step 计算，但干扰你的分析——让你以为有自检需要绕过（机制 4）、以为 step 会被翻倍（机制 6）、让你看不清变量名（机制 7）、让你看不出 pool 被做了 ROT13 变换（机制 8） |

换句话说：机制 1/2/3 在"算数"（累加 step），机制 5 保证你没法改文件，机制 4（自检部分）/6/7/8 让你很难看懂算法。**它们是一个整体**——没有保镖（5），你可以直接改掉 HTML 文件跳过校验；没有障眼法（4/6/7/8），算法一眼就能看穿。

### 3.2 机制一：instrument()——debug condition 累加 step

这是 step 计数器的**主要来源**（贡献了 step 增量的绝大部分）。出题人在源码注释中称之为"performance counter"（性能计数器），但这个名称是误导性的——它不是性能监控工具，而是 **flag 校验算法的核心**，决定了从字符池中取哪个字符。

```javascript
function instrument() {
    f = arguments[0];
    // 给函数 f 添加 debug condition
    debug(f, "window.c && function perf(){ const l = `" + f + "`.length; window.step += l; }() // ...");
    // 篡改检测
    debug(f, "document.documentElement.outerHTML.length !== 14347");
}
```

**逐行解读**：

##### `f = arguments[0];`

`arguments` 是 JavaScript 中每个函数都自动拥有的内置对象——不需要声明，不需要在参数列表中列出。`arguments[0]` 就是传入的第一个参数。

这里等价于 `function instrument(f) { ... }`，出题人用 `arguments[0]` 只是代码风格选择。

调用方式是 `.forEach(instrument)`，所以 `arguments[0]` 每次循环取到的是一个函数对象（如 `Array.isArray`、`Array.prototype.push` 等）。

##### debug condition 字符串拼接

```javascript
"window.c && function perf(){ const l = `" + f + "`.length; window.step += l; }()"
```

这段代码用字符串拼接构造了一个 debug condition。关键在中间的 `` `" + f + "` `` ——它把函数对象 `f` 放在一对反引号中间。

当这个 condition 在 Chrome 中执行时：

1. **字符串拼接阶段**（`instrument()` 被调用时，只在 `anti()` 期间执行一次）：`f` 被自动 `.toString()` 成函数源码字符串，拼进 condition 中。假设 `f` 是 `renderFrame`，condition 变成：
   ```
   "window.c && function perf(){ const l = `function renderFrame() { ... 一大段源码 ... }`.length; window.step += l; }()"
   ```

2. **condition 执行阶段**（每次 `renderFrame()` 被调用时执行）：
   - `` `function renderFrame() { ... }` `` 是一个普通字符串（反引号里没有 `${}`，不做模板替换），值就是源码文本本身
   - `.length` 是**字符串的 length**（字符数），不是函数的 `.length`（参数个数）
   - 所以 `l` 的值就是 `renderFrame` 函数源码的字符总数（比如 3858）
   - `window.step += 3858`

**注意区分两种 `.length`**：

```javascript
function add(a, b) { return a + b; }

add.length           // 2  ← 函数的 length，表示声明的参数个数
`${add}`.length      // 37 ← 字符串的 length，函数源码的字符数
```

debug condition 中用的是第二种——**函数源码字符串的字符数**。

**这段代码做了什么？**

以 `renderFrame` 函数为例，调用 `instrument(renderFrame)` 后，相当于设置了：

```javascript
debug(renderFrame, "window.c && function perf(){ const l = `renderFrame函数的完整源码`.length; window.step += l; }()");
```

当 `renderFrame()` 被调用时：
1. Chrome 先执行 debug condition
2. condition 检查 `window.c`——这个值来自 HTML 第 7 行的 `<meta id="c" ...>` 标签。浏览器会自动把带 `id` 的元素注册为 `window` 的属性，所以 `window.c` 是一个 DOM 元素对象（truthy，永远存在）。注意这不是 `window.cﾠ`（c 后面有 U+FFA0，由 anti() 设置为 `true`），而是普通的 `window.c`——两个完全不同的变量。`window.c &&` 永远为 true，不控制任何行为。出题人故意让这两个名字几乎一样的变量同时出现，让你误以为 debug condition 检查的是 anti() 设置的开关，实际上检查的是一个永远为 true 的 DOM 元素——**这是一种认知混淆：让你以为看懂了，但理解是错的**
3. 执行 `perf()` 函数：取 renderFrame 源码的长度（3858），加到 `window.step`
4. condition 返回 `undefined`（falsy）——因为 IIFE `function perf(){ ... }()` 没有 `return` 语句，返回 `undefined`。`window.c && undefined` = `undefined`（falsy）→ **Chrome 不暂停**，函数正常执行。所以你在 DevTools 中手动输入 flag 不会看到暂停——这是正常的
5. 第二个 debug condition `"document.documentElement.outerHTML.length !== 14347"` 检查 HTML 长度，没改过 HTML 就返回 `false`（falsy）→ 也不暂停

每个被 instrument 的函数都会在每次调用时把**自己的源码长度**加到 step 上：

```
check          →  step += 914   (每次调用)
renderFrame    →  step += 3858  (每次调用)
r              →  step += 119   (每次调用)
shift          →  step += 34    (每次调用)
splice         →  step += 35    (每次调用)
...以此类推
```

**被 instrument 的函数列表**（第 302-304 行）：
```
Array 构造函数的所有方法
Array.prototype 的所有方法（shift、splice、map、join、forEach 等）
String.prototype 的所有方法（split、replace、toString 等）
Math 的所有方法（cos、sin、round、min 等）
console 的所有方法（log、clear 等）
Reflect 的所有方法
check 函数本身
eval 函数
```

### 3.3 机制二：instrumentPrototype()——原型链 getter 劫持

```javascript
function instrumentPrototype(o) {
    Object.entries(Object.getOwnPropertyDescriptors(o))
      .filter(p => p[1].value instanceof Function)
      .forEach(p => Object.defineProperty(o, p[0], {
        get: () => (step++) && p[1].value
      }));
}
```

#### 逐行解读

##### 第一行：`Object.entries(Object.getOwnPropertyDescriptors(o))`

从内向外执行：

1. `Object.getOwnPropertyDescriptors(o)` — 获取 `o`（即 `Array.prototype`）上所有**自身属性**的描述符。每个属性返回一个描述符对象：

```javascript
{
  shift:   { value: ƒ shift(), writable: true, enumerable: false, configurable: true },
  splice:  { value: ƒ splice(), writable: true, enumerable: false, configurable: true },
  map:     { value: ƒ map(), writable: true, enumerable: false, configurable: true },
  length:  { value: 0, writable: false, enumerable: false, configurable: false },
  ...
}
```

2. `Object.entries(...)` — 把上面的对象变成 `[key, descriptor]` 数组：

```javascript
[
  ["shift",   { value: ƒ shift(), ... }],    // p[0]="shift",   p[1]={value: ƒ shift()}
  ["splice",  { value: ƒ splice(), ... }],   // p[0]="splice",  p[1]={value: ƒ splice()}
  ["map",     { value: ƒ map(), ... }],      // p[0]="map",     p[1]={value: ƒ map()}
  ["length",  { value: 0, ... }],            // p[0]="length",  p[1]={value: 0}
  ...
]
```

为什么用 `Object.entries` 而不是 `Object.values`？因为后面 `Object.defineProperty(o, p[0], ...)` 需要 `p[0]`（属性名）来知道要改哪个属性。`Object.values` 只返回值，丢掉了属性名。

##### 第二行：`.filter(p => p[1].value instanceof Function)`

只保留描述符中 `value` 是函数的条目，过滤掉非函数属性（如 `length: 0`、`constructor: ƒ Array()` 等）：

```javascript
// 过滤后：
[
  ["shift",   { value: ƒ shift(), ... }],
  ["splice",  { value: ƒ splice(), ... }],
  ["map",     { value: ƒ map(), ... }],
  // ... 都是函数
]
```

##### 第三行：`.forEach(p => Object.defineProperty(o, p[0], { get: ... }))`

遍历每个过滤后的条目，用 `Object.defineProperty` 把原来的数据描述符替换成访问器描述符（getter）。

以 `shift` 为例，替换前后的对比：

```javascript
// 替换前——数据描述符（直接存函数）
Array.prototype.shift = ƒ shift()

// 替换后——访问器描述符（访问时调函数）
Object.defineProperty(Array.prototype, "shift", {
  get: () => (step++) && p[1].value   // p[1].value 就是原始的 ƒ shift()
});
```

##### getter 内部：`get: () => (step++) && p[1].value`

这行拆成三步：

1. **`step++`** — `step` 就是 `window.step`（全局变量，由 anti() 在第 239 行初始化为 0）。getter 里没定义 `step`，JavaScript 引擎自动到全局作用域 `window` 上找。`++` 是后缀递增，先返回**旧值**，再加 1
2. **`&&`** — 左边是 truthy（step 旧值 ≥ 1）时，继续执行右边；左边是 falsy（step 旧值 = 0）时，短路返回左边的值
3. **`p[1].value`** — 原始函数对象（如 `ƒ shift()`）。JavaScript 中函数是对象，可以像值一样传递。getter 不"替代"原始函数，只是在你**访问属性时**做一步中转：先计数，再把原始函数交出来让你调用

##### 完整调用流程

当你执行 `[1,2,3].shift` 时：

```
1. JavaScript 引擎在数组实例 [1,2,3] 上找 shift → 没有
2. 上溯到 Array.prototype → 找到了 getter
3. getter 执行：
   step++        → step 从 N 变成 N+1，返回旧值 N
   N && ƒ shift()
   → N ≥ 1 时：返回 ƒ shift()（原始函数对象）
   → N = 0 时：返回 0（falsy，短路了）← 问题！
4. 拿到函数对象后，(1,2,3).shift() 调用它
```

> **核心发现**：getter 中的 `step++` 返回旧值。当 step=0 时，`0 && 函数` = 0（falsy），getter 返回 0 而不是原始函数。这意味着**在 step 被重置为 0 后，第一次访问数组方法会失败**！check() 函数通过先执行 `[0].step`（触发 Proxy 使 step 变为 1）来避免这个问题。

### 3.4 机制三：instrumentPrototypeOfPrototype()——Proxy 原型拦截

源码：

```javascript
function instrumentPrototypeOfPrototype(o) {
    const handler = {};
    Reflect.ownKeys(Reflect).forEach(h => 
        handler[h] = (a, b, c) => (step++) && Reflect[h](a, b, c)
    );
    Object.setPrototypeOf(o, new Proxy(Object.getPrototypeOf(o), handler));
}
```

调用方式：

```javascript
instrumentPrototypeOfPrototype(Array.prototype);
```

所以函数内部 `o = Array.prototype`。

下面逐行拆解。

---

#### 第一行：`const handler = {};`

创建一个空的普通 JavaScript 对象。这个对象将用来存放 Proxy 的所有拦截规则。

---

#### 第二行：`Reflect.ownKeys(Reflect).forEach(h => handler[h] = (a, b, c) => (step++) && Reflect[h](a, b, c));`

这行最长，逐段拆。

##### 2.1 `Reflect` 是什么

`Reflect` 是 JavaScript 内置对象，它的每个方法对应一种对象操作：

| Reflect 方法 | 等价于 |
|-------------|--------|
| `Reflect.get(obj, "name")` | `obj.name`（访问属性） |
| `Reflect.set(obj, "name", "x")` | `obj.name = "x"`（设置属性） |
| `Reflect.has(obj, "name")` | `"name" in obj`（检查属性是否存在） |
| `Reflect.deleteProperty(obj, "name")` | `delete obj.name`（删除属性） |
| `Reflect.apply(fn, thisArg, args)` | `fn.apply(thisArg, args)`（调用函数） |
| `Reflect.construct(Fn, args)` | `new Fn(...args)`（构造实例） |
| ... 共 13 个方法 | |

`Reflect` 不是目标对象，它只是"操作对象的工具"。它不存数据，只提供方法。

##### 2.2 `Reflect.ownKeys(Reflect)`

获取 `Reflect` 对象身上所有自身方法的名字，返回一个数组：

```javascript
["get", "set", "has", "deleteProperty", "apply", "construct",
 "getOwnPropertyDescriptor", "defineProperty", "getPrototypeOf",
 "setPrototypeOf", "isExtensible", "preventExtensions", "ownKeys"]
```

一共 13 个方法名。这些名字既是 `Reflect` 的方法名，也是 Proxy handler 支持的拦截操作类型名——这不是巧合，而是 JavaScript 标准的设计：**Proxy handler 的 13 种操作类型，和 `Reflect` 的 13 个方法一一对应。**

##### 2.3 `.forEach(h => ...)`

遍历上面那个数组，`h` 每次循环取一个方法名。`h` 依次是 `"get"`、`"set"`、`"has"`、`"deleteProperty"` ... 直到 13 个全部处理完。

##### 2.4 循环体：`handler[h] = (a, b, c) => (step++) && Reflect[h](a, b, c)`

每次循环给 `handler` 对象加一条拦截规则。以 `h = "get"` 为例：

```javascript
handler["get"] = (a, b, c) => (step++) && Reflect["get"](a, b, c);
```

这是一个箭头函数，拆开看：

- `(a, b, c)` — 三个参数。参数的值由 Proxy 自动传入（后面详细说）
- `step++` — 先把 step 加 1，返回旧值（正数，truthy）
- `&&` — 左边是 truthy，继续执行右边
- `Reflect[h](a, b, c)` — 调用 `Reflect` 对应的方法，执行原始操作并返回结果

再以 `h = "set"` 为例，循环到这次时等价于：

```javascript
handler["set"] = (a, b, c) => (step++) && Reflect["set"](a, b, c);
```

同样的模式：计数，然后执行原始操作。

##### 2.5 出题人为什么不直接写

完全可以直接写，效果一模一样：

```javascript
const handler = {
    get:                (a,b,c) => (step++) && Reflect.get(a, b, c),
    set:                (a,b,c) => (step++) && Reflect.set(a, b, c),
    has:                (a,b,c) => (step++) && Reflect.has(a, b, c),
    deleteProperty:     (a,b,c) => (step++) && Reflect.deleteProperty(a, b, c),
    apply:              (a,b,c) => (step++) && Reflect.apply(a, b, c),
    construct:          (a,b,c) => (step++) && Reflect.construct(a, b, c),
    getOwnPropertyDescriptor: (a,b,c) => (step++) && Reflect.getOwnPropertyDescriptor(a, b, c),
    defineProperty:     (a,b,c) => (step++) && Reflect.defineProperty(a, b, c),
    getPrototypeOf:     (a,b,c) => (step++) && Reflect.getPrototypeOf(a, b, c),
    setPrototypeOf:     (a,b,c) => (step++) && Reflect.setPrototypeOf(a, b, c),
    isExtensible:       (a,b,c) => (step++) && Reflect.isExtensible(a, b, c),
    preventExtensions:  (a,b,c) => (step++) && Reflect.preventExtensions(a, b, c),
    ownKeys:            (a,b,c) => (step++) && Reflect.ownKeys(a, b, c),
};
```

出题人用 `forEach` 只是因为 13 条规则的格式完全一样，只有方法名不同，用循环生成更简洁。这是代码风格的选择，不是技术上的必须。

##### 2.6 循环结束后 handler 的内容

```javascript
handler = {
    get:                (a,b,c) => (step++) && Reflect.get(a, b, c),
    set:                (a,b,c) => (step++) && Reflect.set(a, b, c),
    has:                (a,b,c) => (step++) && Reflect.has(a, b, c),
    deleteProperty:     (a,b,c) => (step++) && Reflect.deleteProperty(a, b, c),
    apply:              (a,b,c) => (step++) && Reflect.apply(a, b, c),
    construct:          (a,b,c) => (step++) && Reflect.construct(a, b, c),
    getOwnPropertyDescriptor: (a,b,c) => (step++) && Reflect.getOwnPropertyDescriptor(a, b, c),
    defineProperty:     (a,b,c) => (step++) && Reflect.defineProperty(a, b, c),
    getPrototypeOf:     (a,b,c) => (step++) && Reflect.getPrototypeOf(a, b, c),
    setPrototypeOf:     (a,b,c) => (step++) && Reflect.setPrototypeOf(a, b, c),
    isExtensible:       (a,b,c) => (step++) && Reflect.isExtensible(a, b, c),
    preventExtensions:  (a,b,c) => (step++) && Reflect.preventExtensions(a, b, c),
    ownKeys:            (a,b,c) => (step++) && Reflect.ownKeys(a, b, c),
};
```

13 条规则，每一条都是同一个模式：**先 step++，然后调用 Reflect 对应的方法执行原始操作。**

注意 handler 里的名字（`get`、`set`、`has` 等）是**操作类型**，不是属性名。`get` 表示"访问属性"这个动作，不管访问的是什么属性名，只要操作类型是"访问属性"，就走 `handler.get` 这条规则。属性名作为第二个参数 `b` 传进去，handler 不需要提前知道属性名是什么。

---

#### 第三行：`Object.setPrototypeOf(o, new Proxy(Object.getPrototypeOf(o), handler));`

这行代码从内到外执行，按执行顺序拆：

##### 3.1 `Object.getPrototypeOf(o)`

`o` 是 `Array.prototype`。这行获取 `Array.prototype` 的上级原型：

```javascript
Object.getPrototypeOf(Array.prototype)
// 结果：Object.prototype
```

##### 3.2 `new Proxy(Object.prototype, handler)`

用 `Object.prototype` 作为目标对象，handler 作为拦截规则，创建一个 Proxy 对象。

Proxy 接收两个参数：
- 第一个参数：**目标对象**，这里是 `Object.prototype`。Proxy 不会修改这个对象，所有操作通过 handler 转发给它
- 第二个参数：**拦截规则**，这里是 handler，里面有 13 条规则

Proxy 对象本身不存任何数据，它只是一个中间人。所有对它的操作都转发给目标对象，但中间可以加自己的逻辑（比如 `step++`）。

**Proxy 怎么使用 handler**：当有人对 Proxy 对象做任何操作时，Proxy 不直接操作目标对象，而是先调用 handler 里对应的方法。比如有人访问 Proxy 对象的 `toString` 属性：

```
1. Proxy 发现有人要"访问属性"（操作类型：get）
2. Proxy 找到 handler 里的 "get" 这条规则
3. Proxy 调用 handler.get，并且 Proxy 自动传入三个参数：
   handler.get(目标对象, "toString", 最初发起访问的对象)
   也就是：
   handler.get(Object.prototype, "toString", pool)

4. handler.get 的函数体执行：
   (step++) && Reflect.get(Object.prototype, "toString", pool)
   → step++，然后从 Object.prototype 上取 toString，返回这个函数

5. Proxy 把 handler.get 的返回值返回给调用者
```

参数 `a`、`b`、`c` 的值由 Proxy 自动传入，不是代码里写死的。`a` 永远是创建 Proxy 时指定的目标对象（`Object.prototype`），因为 Proxy 每次调用 handler 时都会自动把目标对象作为第一个参数传进去。这就是为什么 handler 里能正确地从 `Object.prototype` 上获取属性——`a` 就是 `Object.prototype`，是 Proxy 传进来的。

不同操作类型传入的参数不同：

| handler 中的操作类型 | a | b | c |
|---|---|---|---|
| `get` | 目标对象 `Object.prototype` | 属性名（如 `"toString"`） | 接收者（发起访问的对象） |
| `set` | 目标对象 `Object.prototype` | 属性名（如 `"toString"`） | 要设置的值 |
| `has` | 目标对象 `Object.prototype` | 属性名（如 `"toString"`） | `undefined`（没用到） |
| `deleteProperty` | 目标对象 `Object.prototype` | 属性名（如 `"toString"`） | `undefined`（没用到） |
| `apply` | 目标函数 | `this` 指向 | 参数数组 |

出题人统一写 `(a,b,c)` 三个参数，是因为大部分操作最多用 3 个参数。有的操作只用 2 个（`has`、`deleteProperty`），第三个 `c` 就是 `undefined`，不影响执行。有的操作需要 4 个（`set` 实际有 4 个参数），第 4 个丢了，但 `Reflect.set` 只传前 3 个也能正常工作。

##### 3.3 `Object.setPrototypeOf(Array.prototype, Proxy对象)`

把 `Array.prototype` 的上级原型从 `Object.prototype` 替换为这个 Proxy 对象。

##### 3.4 函数调用的参数怎么传？

上面只展示了"访问属性"（get）这一步。但实际代码中经常是访问完属性后**立刻调用**，比如 `pool.splice(0, 1)`。这里发生的是**两件事**：

**第一件事：访问属性 `pool.splice`** → 触发 `handler.get`

```
pool.splice         ← 访问属性
→ Proxy 拦截"访问属性"操作（操作类型：get）
→ handler.get(Object.prototype, "splice", pool)
→ step++，返回 splice 函数对象

此时 (0, 1) 还没出场。handler.get 只负责"找到函数"，不负责传参。
```

**第二件事：调用函数 `splice(0, 1)`** → 触发 `handler.apply`

```
splice(0, 1)        ← 调用函数
→ Proxy 拦截"调用函数"操作（操作类型：apply）
→ handler.apply(目标函数, pool, [0, 1])
                                 ↑ 这就是参数！Proxy 把调用参数包装成数组作为第三个参数 c

→ handler.apply 函数体执行：
  (step++) && Reflect.apply(目标函数, pool, [0, 1])
  → step++，然后执行原始的 splice(0, 1) 调用
```

所以参数没有丢——属性访问（get）和函数调用（apply）是两个独立的操作，Proxy 分别拦截，各计一次 step。一次 `pool.splice(0, 1)` 会触发 **两次** step++（一次 get + 一次 apply）。

---

#### 原型链变化

**之前**：

```
pool（数组实例，比如 [1,2,3]）
  → pool.__proto__ = Array.prototype（有 splice、push、map 等）
    → Array.prototype.__proto__ = Object.prototype（有 toString、valueOf 等）
      → Object.prototype.__proto__ = null（到头了）
```

**之后**：

```
pool（数组实例）
  → pool.__proto__ = Array.prototype（有 splice、push、map 等）
    → Array.prototype.__proto__ = Proxy对象（handler 拦截所有操作，每次 step++）
      → Proxy对象内部代理的目标对象 = Object.prototype（有 toString、valueOf 等）
        → Object.prototype.__proto__ = null（到头了）
```

Proxy 对象被插入到了原型链中，它既是 Proxy 对象，也是原型链中的一环，被代理的对象是 Object.prototype。


**Proxy 为什么不需要自己有 toString、valueOf 这些函数？**

JavaScript 访问对象属性时，如果自身没有，就沿着原型链往上找。原型链上是什么，就按什么的规则来：

原型是普通对象 → 正常返回属性
原型是 Proxy → 触发 handler 拦截
原型是 null → 到头了，返回 undefined
JavaScript 引擎不关心原型链上那个东西"是什么类型"，它只是按照统一的规则取属性。

对于 Proxy 的接口调用，这是 JavaScript 标准定义的 Proxy 机制——Proxy 从来不"拥有"任何属性。当你对 Proxy 对象做任何操作（访问属性、调用函数、检查属性是否存在等），JavaScript 引擎**不会在 Proxy 对象上查找属性**，而是直接走 handler 拦截。handler 拿到你想要的属性名（如 `"toString"`），通过 `Reflect.get` 去**目标对象**（`Object.prototype`）上取。目标对象上有什么，Proxy 就能让你访问到什么。

---

#### 原型是什么

原型就是一个普通的 JavaScript 对象。没有特殊标记，没有特殊类型。任何对象都可以当原型——就是把它放到另一个对象的 `__proto__` 位置上。属性查找在对象自身找不到时，就去原型上找，找不到就去原型的原型上找，直到 `null` 为止。

---

#### 实际触发时的完整过程

假设题目代码执行 `pool.splice(0, 1)`：

**第1步**：JavaScript 引擎在 `pool` 自身上找 `splice` → 没有。

**第2步**：去 `pool.__proto__`（`Array.prototype`）上找 `splice` → 找到了。这一步没有经过 Proxy，因为 `splice` 在 `Array.prototype` 上就找到了。

**第3步**：执行 `splice` 函数。`splice` 内部需要访问数组的各种属性，比如 `length`。`length` 在 `pool` 自身上就有，直接返回，不经过 Proxy。

**第4步**：但 `splice` 内部可能还需要访问 `toString` 之类的方法。这些方法不在 `pool` 自身上，也不在 `Array.prototype` 上，而在 `Object.prototype` 上。查找过程：

```
第1站：pool 自身上找 toString → 没有
第2站：Array.prototype 上找 toString → 没有
第3站：Array.prototype.__proto__（即 Proxy对象）上找 → 遇到 Proxy！
```

**第5步**：JavaScript 引擎发现第3站是一个 Proxy 对象，不会直接在它上面找属性，而是调用 `handler.get`：

```
引擎调用：handler.get(目标对象, "toString", pool)
也就是：  handler.get(Object.prototype, "toString", pool)
```

参数来源：
- `a = Object.prototype`：创建 Proxy 时指定的第一个参数（目标对象），引擎自动传入
- `b = "toString"`：要访问的属性名，引擎自动传入
- `c = pool`：最初发起属性访问的对象，引擎自动传入

**第6步**：handler.get 的函数体执行：

```javascript
(a, b, c) => (step++) && Reflect.get(a, b, c)
```

代入实际参数：

```javascript
(Object.prototype, "toString", pool) => (step++) && Reflect.get(Object.prototype, "toString", pool)
```

执行过程：
1. `step++` — step 从比如 100 变成 101
2. `Reflect.get(Object.prototype, "toString", pool)` — 从 `Object.prototype` 上获取 `toString` 属性，返回这个函数

`Reflect.get(目标对象, 属性名, receiver)` 就是从目标对象上找属性，找不到就沿目标对象的原型链继续找。你传 `Object.prototype`，它就从 `Object.prototype` 找。`Object.prototype` 上有 `toString`，找到了，返回它。第三个参数 `receiver`（这里是 `pool`）决定如果属性是 getter，getter 里的 `this` 指向谁。普通属性（如 `toString` 函数）不受影响，但传了更安全。

**第7步**：JavaScript 引擎拿到 `toString` 函数，返回给 `splice` 内部使用。

**第8步**：`splice` 继续执行，如果还需要访问其他 `Object.prototype` 上的属性，每次都重复第4-7步的过程，每次 `step++`。

---

#### 完整调用链总结

```
代码：pool.toString

JavaScript 引擎查找属性：
  pool 自身 → 没有 toString
  Array.prototype → 没有 toString
  Proxy对象 → Proxy 拦截！
    │
    ▼
  引擎调用 handler.get(Object.prototype, "toString", pool)
    │
    ▼
  handler.get 内部：
    1. step++
    2. Reflect.get(Object.prototype, "toString", pool)
       → 从 Object.prototype 上找到 toString，返回它
    │
    ▼
  handler.get 返回 Object.prototype.toString
    │
    ▼
  JavaScript 引擎把 Object.prototype.toString 返回给代码
```

对 `pool.toString` 的调用者来说，结果和不加 Proxy 完全一样（拿到了 toString 函数），但中间偷偷多了一步 `step++`。

---

#### 效果总结

出题人在 `Array.prototype` 和 `Object.prototype` 之间插入了一个 Proxy 对象。这个 Proxy 对象：

- **对外表现**：和 `Object.prototype` 一模一样（因为 handler 里用 Reflect 执行了原始操作，从 `Object.prototype` 上获取属性并返回）
- **暗中多做的事**：每次经过时 `step++`

对 `pool.splice(...)` 的调用者来说，结果完全正常。但 `splice` 内部每访问一次 `Object.prototype` 上的属性，step 就多 1。这就是"间谍"——干一样的事，偷偷记一笔。

### 3.5 机制四：check() 第一行的 Function tagged template

```javascript
// check() 函数的第一行（第 255 行）：
Function`[0].step; if (window.step == 0 || check.toString().length !== 914) while(true) debugger;`
```

**表面上看**：这行代码创建了一个函数，函数体包含自检逻辑（检查 step 是否为 0、check 源码长度是否为 914），如果检查失败就无限 debugger。

**实际上**：`Function\`...\`` 是 tagged template，`Function` 是标签函数。`Function(strings)` 会用字符串作为函数体**创建一个新函数**，但**不调用它**。新函数被创建后就丢弃了（没有赋值给任何变量），函数体里的自检代码**从未执行**。

```javascript
// 证据：Function tagged template 不执行函数体
let sideEffect = false;
Function`sideEffect = true`;  // 创建函数，不调用
sideEffect;                    // false —— 函数体没有执行
```

**那这行代码到底有什么作用？** `Function` 本身被 `instrument()` 加了 debug condition。调用 `Function(...)` 创建函数时，debug condition 触发，累加了 `Function` 的源码长度到 step。所以这行代码的真正作用是：**通过调用 Function 触发 debug condition，累加了一部分 step**。自检代码只是障眼法——让你以为有防篡改机制，花时间去研究怎么绕过，但其实它根本不执行。

```
这行代码的实际执行流程：
1. Function(strings) 被调用 → 创建新函数对象
2. Function 的 debug condition 触发 → step += Function 的源码长度
3. 新函数对象被丢弃（没有赋值、没有调用）
4. 函数体里的自检代码（while(true) debugger）从未执行
```

### 3.6 机制五：HTML 长度校验

```javascript
// instrument() 中的第二个 debug condition（第 285 行）：
debug(f, "document.documentElement.outerHTML.length !== 14347");
```

每个被 instrument 的函数都有这个 debug condition。当 HTML 被修改（长度不等于 14347）时，condition 返回 true → Chrome 暂停执行（断点触发）。

这是防止你直接修改 HTML 文件来绕过反调试。

### 3.7 机制六：double() 障眼法

```javascript
// 第 264 行：
const double = Function.call`window.step[U+FFA0] *= 2`;
```

**表面上看**：`double()` 会把 `window.step` 乘以 2。

**实际上**：`double()` 是一个**空函数**，什么都不做。原因如下：

1. `Function.call\`window.step[U+FFA0] *= 2\`` — 这是 tagged template
2. tagged template 会把模板字符串包装成数组传给标签函数：`Function.call(["window.step[U+FFA0] *= 2"])`
3. `call` 的语法是 `fn.call(thisArg, arg1, ...)`。传入的数组 `["window.step[U+FFA0] *= 2"]` 被当作 `thisArg`（this 指向），没有额外参数传给 `Function`
4. 所以等价于 `Function()`，创建了一个**空函数体**的函数
5. 验证：`double.toString()` 输出 `function anonymous() { }`——函数体是空的

```javascript
// 题目写法
const double = Function.call`window.step[U+FFA0] *= 2`;
// double 的函数体是空的，调用 double() 什么都不做

// 对比：如果出题人想创建有函数体的函数，应该写：
const double2 = Function`window.step[U+FFA0] *= 2`;
// double2 的函数体是 "window.step[U+FFA0] *= 2"（但仍然修改的是错误的变量）
```

**两层障眼法**：
- **第一层**：代码中写了 `window.step[U+FFA0] *= 2`，看起来会修改 step（但 [U+FFA0] 使其变成另一个变量）
- **第二层**：由于 `Function.call` + tagged template 的特性，连这行代码都没有被执行——函数体是空的，调用 `double()` 什么都不做

**这是一个精心设计的障眼法**——代码中写了看似翻倍 step 的逻辑，但实际上双重保护确保它什么影响都没有。

### 3.8 机制七：U+FFA0 隐藏标识符

题目大量使用不可见 Unicode 字符来混淆代码。VS Code 中这些字符会显示为黄框。

#### 两种不可见字符，两种用途

源码中使用的不可见字符分为两类：

**第一类：U+FFA0（HALFWIDTH HANGUL FILLER，半角韩文填充符）——当变量名用**

```javascript
window.cﾠ = true;    // 实际是 window["c" + U+FFA0]，不是 window.c
let iﾠ = 1337;       // 实际是变量 "i" + U+FFA0，不是变量 i
ﾠ = function(s) { ... }  // 变量名就是 U+FFA0，即 ROT13 函数
```

**第二类：U+2000-U+200A（各种 Unicode 空格）——当代码空格用**

```javascript
// 源码第 243-244 行实际内容（用 [U+XXXX] 标注不可见字符）：
window.r[U+2002]//[U+2003]ROT47
[U+2003]=[U+2000]function(s)[U+2003]{
```

这些字符在代码中起空格的作用，让代码看起来正常排版，但实际上每个"空格"都是不同的不可见字符。

#### 为什么只有 U+FFA0 能当变量名

JavaScript 对变量名有规则：只有 Unicode 分类为 **ID_Start**（标识符起始）和 **ID_Continue**（标识符续写）的字符才能当变量名。

| 字符 | Unicode 分类 | 能当变量名？ | 用途 |
|------|-------------|------------|------|
| U+FFA0 | 韩文字母（ID_Start + ID_Continue） | ✅ 能 | 伪装成变量名的一部分 |
| U+2002 | 空格类符号（Zs） | ❌ 不能 | 伪装成代码空格 |
| U+2003 | 空格类符号（Zs） | ❌ 不能 | 伪装成代码空格 |
| U+2005 | 空格类符号（Zs） | ❌ 不能 | 伪装成代码空格 |

```javascript
// ✅ U+FFA0 是合法的标识符字符
let ﾠ = function() {};  // 不报错

// ❌ U+2002 不是合法的标识符字符
let   = function() {};  // SyntaxError: Invalid or unexpected token
```

出题人只在需要当变量名的地方用 U+FFA0，其他地方用 U+2002、U+2003 等只起空格作用的不可见字符。

#### `window.k` 不是赋值

源码第 248-249 行：

```javascript
window.k[U+2005]// ROT13 - TODO: use this for an additional encryption layer
[U+FFA0]=[U+2003]function(s)[U+2009]{
```

第 248 行 `window.k` 只是一个表达式语句（访问 `window.k`），没有 `=`，不是赋值。真正的赋值是第 249 行的 `ﾠ = function(s) { ... }`，变量名是 `ﾠ`（U+FFA0）。

出题人故意在第 248 行写 `window.k` 让读者以为是赋值给 `k`，但实际赋值的是不可见字符 `ﾠ`。这也是混淆手段之一。

#### 这些隐藏标识符的效果

- 代码阅读时容易忽略关键变量（`window.c` vs `window.cﾠ`）
- 搜索 `window.c` 找不到 `window.cﾠ`
- 以为 `window.c` 是一个布尔值，实际上是另一个完全不同的变量
- VS Code 中黄框到处都是，反而让人分不清哪些是变量名、哪些只是空格

### 3.9 机制八：tagged template 隐式 ROT13

```javascript
// 第 262 行：
let pool = ﾠ`?o>\`Wn0o0U0N?05o0ps}q0|mt\`ne\`us&400_pn0ss_mph_0\`5`;
```

**表面上看**：给 pool 赋一个普通的模板字符串。

**实际上**：`ﾠ`（U+FFA0）是 ROT13 函数的变量名。它作为 tagged template 的标签函数，对模板字符串的内容执行了 ROT13 变换。

所以这行代码等价于：
```javascript
let pool = rot13("?o>`Wn0o0U0N?05o0ps}q0|mt`ne`us&400_pn0ss_mph_0`5");
```

然后第 263 行又执行了 ROT47：
```javascript
pool = r(pool).split('');
```

最终 pool 经过 **ROT13 → ROT47** 两层变换：

```
原始字符串:  ?o>`Wn0o0U0N?05o0ps}q0|mt`ne`us&400_pn0ss_mph_0`5
     ↓ ROT13
中间结果:    ?b>`Ja0b0H0A?05b0cf}d0|zg`ar`hf&400_ca0ff_zcu_0`5
     ↓ ROT47
最终 pool:   n3m1y2_3_w_pn_d3_47N5_MK812C197Uc__042_770K4F0_1d
```

### 3.10 所有机制如何协同工作

现在我们理解了每个机制，来看看它们如何共同决定 flag 的计算：

```
anti(debug) 执行后:
  ├─ window.step = 0 (然后经过初始化变为 144)
  ├─ 所有函数被 instrument → debug condition 就绪
  ├─ Array.prototype 被 getter 劫持
  └─ Array.prototype 的原型被 Proxy 包裹

unlock("CTF{密码}") 执行时:
  ├─ 提取密码，设置 window.flag
  └─ 调用 check()
       ├─ window.step = 0; [0].step;  → step = 1 (Proxy 触发)
       ├─ pool = ROT13`...` → ROT47 → 得到 49 字符的字符池
       └─ while 循环 (49 次):
            ├─ j = (i * 16807 + step) % 2147483647  // 伪随机数
            ├─ 比较 flag[0] 与 pool[j % pool.length]
            ├─ 如果匹配:
            │    ├─ flag.shift()       → getter: step++   → Proxy: step++
            │    ├─ pool.splice(idx,1)  → getter: step++   → Proxy: step++
            │    ├─ renderFrame()       → debug condition: step += 3858
            │    │   └─ renderFrame 内部调用数十个 instrumented 函数
            │    │       每个都通过 debug condition 增加大量 step
            │    └─ double()            → no-op (修改的是 window.stepﾠ)
            └─ 如果不匹配: 死循环

最终: step 从 1 增长到 ~29529 (49 轮后)，小于 1000000 的上限
```

---

## 第四章：破解过程——从失败到成功

这一章记录了完整的破解过程，包括大量失败尝试和关键转折点。**失败记录是这篇 writeup 最有价值的部分**——它们展示了错误的思路是如何一步步被纠正的。

### 4.1 第一步：静态分析——阅读源码

首先阅读 HTML 源码（328 行），识别出关键信息：

**已识别**：
- 3 个核心函数：anti()、check()、unlock()
- 8 个反调试/混淆机制
- step 计数器是 flag 校验的核心
- U+FFA0 隐藏标识符的存在
- double() 是障眼法

**未识别（后来导致错误）**：
- pool 的 tagged template 语法中 `ﾠ` 是标签函数，意味着隐式的 ROT13 调用

### 4.2 关键转折点：发现 pool 的 tagged template

在分析第 262 行时：
```javascript
let pool = ﾠ`?o>\`Wn0o0U0N?05o0ps}q0|mt\`ne\`us&400_pn0ss_mph_0\`5`;
```

我正确地识别了 `ﾠ`（U+FFA0）是 ROT13 函数，也理解了它是 tagged template 的标签函数。**在最早期的版本中（v294-v295），我使用了包含 ROT13+ROT47 的正确 pool 计算**，通过 `window['\uFFA0'](String.fromCharCode(...))` 的方式。

### 4.3 最大的错误：误删 ROT13 步骤

在版本 v306 中，我"重新分析"源码时犯了一个致命错误。

**当时的推理过程**：
1. 看到第 262 行：`let pool = ﾠ\`...\`;`
2. 看到第 263 行：`pool = r(pool).split('');`
3. **错误推理**：我认为第 262 行只是赋值一个模板字符串，第 263 行才是唯一的变换（ROT47）
4. **忽略了**：`ﾠ` 不是普通空格，而是 ROT13 函数名，作为 tagged template 的标签在隐式调用

**错误结果**：
```
正确的 pool（ROT13+ROT47）: n3m1y2_3_w_pn_d3_47N5_MK812C197Uc__042_770K4F0_1d
错误的 pool（仅ROT47）:     n@m1(?_@_&_}n_d@_ADNB_M>E1?61FDUc__0A?_DD0>A90_1d
```

错误的 pool 包含 `(`、`&`、`}`、`>` 等字符，这些都不在 unlock 的正则表达式 `[0-9a-zA-Z_@!?-]` 范围内。

### 4.4 失败原因分析：为什么几十个版本全算错了

从 v306 到 v325（约 20 个版本），所有计算都基于错误的 pool。这期间产生了各种错误 flag：

```
v307: CTF{_U01@&dM?m_0_D9_}F_?6>@0nd1_N(@cDn>_A1_B1DEAA_D_?}  ← 包含 & } > ( @
v313: CTF{1M_A_6D9_}1A(@?_AND1_d@EUF_D?1c>B_d0nD_&0?>_0n_m@}  ← 包含 & } > ( @
v322: CTF{@__>&1?@?AB6m__>(1?UFc1DndD__D90DA@_Mn}__E0N01_dA}  ← 包含 & } > (
```

这些 flag 看起来"合理"，但全部包含不在正则范围内的字符。**如果我当时用 unlock() 的正则验证一下，就能立刻发现 pool 计算错误。**

还有一个系统性问题：**我过度关注了 step delta 的精确测量，而忽略了 pool 计算的正确性**。花了大量时间在 debug condition context vs 直接调用的 step 差异上，但真正的问题是 pool 本身就算错了。

### 4.5 最终突破：回归正确的 pool 计算

在 v326 中，我重新审视第 262 行，正确识别了 tagged template：

```javascript
// 使用和 check() 完全一样的方式计算 pool
INIT = "... var pool = window['\\uFFA0']`?o>\\`Wn0o0U0N?05o0ps}q0|mt\\`ne\\`us&400_pn0ss_mph_0\\`5`; "
       "pool = r(pool).split(''); ..."
```

**为什么之前会错？** 因为我看第 262 行 `let pool = ﾠ\`...\`;` 时，肉眼看不出 `ﾠ`（U+FFA0）是一个函数名。它看起来像普通空格，所以我觉得这行就是给 pool 赋一个字符串。第 263 行 `pool = r(pool).split('')` 才是变换——但只看到了 ROT47，漏掉了 ROT13。

**这次怎么发现的？** 用 `window['\uFFA0']` 显式调用，确认了 `ﾠ` 确实是 ROT13 函数。然后意识到 tagged template 会自动调用它。

**结果**：
```
Pool after ROT13: ?b>`Ja0b0H0A?05b0cf}d0|zg`ar`hf&400_ca0ff_zcu_0`5
Pool after ROT47: n3m1y2_3_w_pn_d3_47N5_MK812C197Uc__042_770K4F0_1d
```

所有字符都是 `[0-9a-zA-Z_]` 范围内的！通过了 unlock 的正则验证。

在 debug condition context 中运行正向计算，得到：
```
Flag: CTF{1M_4_C7F_p14y32_4N71_d38U9_721cK5_d0n7_w02K_0n_m3}
Verify: ok=True, matched=49, step=29529
```

### 4.6 另一个关键教训：不要清除 intervals

在 v327-v328 中，pool 计算对了，但验证时还是失败。原因是执行 `anti(debug)` 后，我习惯性地加入了清除 interval 的代码：

```python
# ❌ 错误操作
cdp.send("Runtime.evaluate", {
    "expression": "var _m=setTimeout(function(){},0);for(var _i=0;_i<=_m;_i++){clearInterval(_i)};",
})
```

这破坏了 anti-debug 机制。`anti()` 内部用 `setInterval(renderFrame, ...)` 启动了一个定时器，清除它后 step 计数器的行为发生了变化——从 144 变成了 1。

**为什么清除 interval 会影响 step？** 因为 `anti()` 执行完成后，`setInterval(renderFrame, ...)` 还在后台运行。在 `unlock(flag)` 被调用之前，renderFrame 已经执行了好几轮，每一轮都通过 debug condition 累加了 step。清除了 interval 后，后台的 renderFrame 不再执行，step 就少了这些增量。

在 v333 中，我**去掉了所有多余操作**，只做两件事：
1. `anti(debug)`
2. `unlock(flag)`

**结果直接成功**。step=144，success=true，alert 弹出。

> **核心教训**：应该先尝试最简单的方式，而不是一开始就假设会崩溃然后做各种预防措施。过多的人为干预反而破坏了正常运行环境。

### 4.6.1 最终成功方案的完整逻辑

#### 核心思路

check() 函数用一个 while 循环逐个匹配 flag 的字符。它用线性同余算法（`j = (i * 16807 + step) % 2147483647`）算出一个下标 `j`，然后检查 flag 的第一个字符是否等于 pool 中第 `j % pool.length` 个字符。

**逆向思路**：既然 check() 是从 pool 中按特定顺序取字符和 flag 比较，那我们可以**反过来**——用同样的算法从 pool 中逐个取出字符，拼成 flag。关键问题是 step 每轮变化多少。答案是：**不需要知道**。只要你在 Chrome 中注入代码，和 check() 走完全一样的路径，Chrome 会自己帮你算 step。

#### 破解步骤

##### 步骤 1：算出 pool

读源码第 262-263 行，识别两层编码：

```javascript
let pool = ﾠ`?o>\`Wn0o0U0N?05o0ps}q0|mt\`ne\`us&400_pn0ss_mph_0\`5`;  // 第 262 行
pool = r(pool).split('');                                                  // 第 263 行
```

- 第 262 行：`ﾠ`（U+FFA0）是 ROT13 函数名，作为 tagged template 的标签函数隐式调用 → pool 先经过 ROT13
- 第 263 行：`r()` 是 ROT47 函数 → pool 再经过 ROT47

```
原始字符串:  ?o>`Wn0o0U0N?05o0ps}q0|mt`ne`us&400_pn0ss_mph_0`5
     ↓ ROT13
中间结果:    ?b>`Ja0b0H0A?05b0cf}d0|zg`ar`hf&400_ca0ff_zcu_0`5
     ↓ ROT47
最终 pool:   n3m1y2_3_w_pn_d3_47N5_MK812C197Uc__042_770K4F0_1d  (49个字符)
```

验证：所有字符都在 `[0-9a-zA-Z_]` 范围内（符合 unlock 的正则）。

**这里的坑**：如果漏掉 ROT13（肉眼看不出 `ﾠ` 是函数名），pool 包含非法字符，后续全错。详见 [4.3 最大的错误](#43-最大的错误误删-rot13-步骤)。

##### 步骤 2：理解 check() 的初始状态

源码第 261 行（变量名实际是 `iﾠ`，i 后面有 U+FFA0）：

```javascript
let iﾠ = 1337, j = 0;   // i 是线性同余生成器的种子，出题人硬编码
```

check() 开头还会：
- `window.step = 0` → 重置 step
- `[0].step` → 触发 Proxy → step 从 0 变成 1

所以初始状态：`i=1337`，`step=1`。

##### 步骤 3：在 Chrome 中注入代码正向计算 flag

**为什么要在 Chrome 中算？** 因为每匹配一个字符后，`shift()`、`splice()`、`renderFrame()` 这些操作都会触发 debug condition / getter / Proxy 累加 step。step 的增量取决于 Chrome 内部的执行细节（函数源码长度、嵌套抑制、Proxy 拦截范围），在 Python 中手动模拟不可能算对。**在 Chrome 中执行，Chrome 自己帮你算 step，没有任何偏差。**

**注入代码是什么意思？** 就是通过 Playwright 的 CDP 在页面中执行一段 JavaScript，效果等同于你在 DevTools Console 中手动输入这段代码：

```python
# Playwright 中注入代码的方式
result = cdp.send("Runtime.evaluate", {
    "expression": "1 + 2",        # 这段 JS 代码被送到 Chrome 中执行
    "returnByValue": True,
})
# Chrome 返回: 3
```

**为什么不直接用 check()？** 因为 check() 是**验证** flag 的，不是**生成** flag 的。看 check() 的核心循环：

```javascript
// check() 的 while 循环——验证一个已知的 flag 是否正确
while (!window.success) {
    j = ((i || 1) * 16807 + window.step) % 2147483647;  // ① 计算 j
    
    if (flag[0] == pool[j % pool.length]) {  // ② 对比：用户传入的 flag 和 pool 中的字符
        i = j;
        flag.shift();          // ③ 移除 flag 首字符
        pool.splice(idx, 1);   // ④ 移除 pool 中对应字符 → step++
        renderFrame();         // ⑤ 渲染一帧 → step 大幅增加
        // ...
    }
    // ② 不匹配 → 死循环，什么也不返回
}
```

check() 做了三件事：① 算 j、② 对比 flag 和 pool、③④⑤ 推进 step。其中第 ② 步需要 flag 已经存在（由 unlock() 传入），check() 只告诉你"对"或"不对"，不会告诉你 flag 应该是什么。

**注入代码的做法：去掉第 ② 步的验证逻辑，只保留 ①③④⑤ 的计算逻辑，改成直接从 pool 取字符**：

```
check() 做的事：                        注入代码做的事：
                                       
① j = (i * 16807 + step) % ...         ① j = (i * 16807 + step) % ...     ← 一样
② flag[0] == pool[j%len]  → 对比      ② ch = pool[j%len]  → 直接取       ← 改了
③ flag.shift()                         （不需要，我们没有 flag 要移除）     ← 去掉
④ pool.splice(idx, 1) → step++        ③ pool.splice(idx, 1) → step++     ← 一样
⑤ renderFrame() → step 大幅增加        ④ renderFrame() → step 大幅增加    ← 一样
```

关键：**推进 step 的操作（pool.splice + renderFrame）完全保留，和 check() 一模一样**。所以 step 的增长路径不变，每轮结束后 `window.step` 的值和 check() 里一模一样，下一轮算出的 `j` 也一样。

**具体操作**：

1. 用 Playwright 打开 Chrome
2. 启用 `Debugger.enable`（让 debug condition 能执行）
3. 执行 `anti(debug)` — 让所有机制（debug condition、getter 劫持、Proxy）就位
4. 通过 CDP 注入以下代码：

```javascript
// 去掉 check() 的验证逻辑，只保留计算逻辑，直接从 pool 取字符拼成 flag
(function() {
    window.step = 0;   // 和 check() 一样重置
    [0].step;          // 触发 Proxy，step → 1
    
    // 和 check() 一样的方式计算 pool
    var pool = window['\uFFA0']`?o>\`Wn0o0U0N?05o0ps}q0|mt\`ne\`us&400_pn0ss_mph_0\`5`;
    pool = r(pool).split('');
    
    var i = 1337, j = 0;
    var flag = '';
    
    for (var round = 0; round < 49; round++) {
        // ① 算 j——和 check() 一样
        j = ((i || 1) * 16807 + window.step) % 2147483647;
        var idx = j % pool.length;
        
        // ② 直接从 pool 取字符（check() 里是对比，我们改成直接取）
        var ch = pool[idx];
        flag += ch;
        
        i = j;
        // ③ 和 check() 一样移除已匹配字符 → 触发 getter (step++) + Proxy (step++)
        pool.splice(idx, 1);
        
        // ④ 和 check() 一样渲染一帧 → 触发 debug condition → step 大幅增加
        renderFrame();
    }
    
    return 'CTF{' + flag + '}';
})();
```

Chrome 执行这段代码后，返回的就是正确的 flag。

**这段代码为什么能算对？** 因为它和 check() 走**完全一样的执行路径**：

```
check() 的 while 循环里每次匹配成功后：
  flag.shift()       → 触发 getter + Proxy → step++
  pool.splice()      → 触发 getter + Proxy → step++
  renderFrame()      → 触发 debug condition → step += 函数源码长度 × 几十个函数

注入代码的 for 循环里每次迭代：
  pool.splice()      → 同样触发 getter + Proxy → step++    ← 一样
  renderFrame()      → 同样触发 debug condition → step +=   ← 一样
```

step 的增长完全由 Chrome 内部的机制驱动，不需要你在 Python 中手动算。每轮结束后 `window.step` 的值和 check() 里一模一样，所以下一轮的 `j = (i * 16807 + step) % 2147483647` 也一样，取出的字符就是正确的。

##### 步骤 4：用 unlock() 验证

把步骤 3 算出的 flag 传给 `unlock()`，让 Chrome 自己跑一遍 check() 验证。如果弹出 alert，说明 flag 正确。

```
执行 unlock("CTF{1M_4_C7F_p14y32_4N71_d38U9_721cK5_d0n7_w02K_0n_m3}")
→ 弹出 alert: "JS Safe opened! Content:"
→ 验证成功！
```

#### 一句话总结破解思路

**源码里已经给了所有信息**：pool 的编码方式（ROT13+ROT47）、step 的初始值（0 → 1）、线性同余算法的种子（1337）。你只需要在 Chrome 中注入代码，复用 check() 的算法和执行环境，Chrome 自己帮你处理 step 的累加，49 轮后就能得到正确的 flag。

### 4.7 机制复盘：每个机制让我走了哪些弯路

这道题前后花了一周、写了 300+ 个版本的脚本。回头看，所有弯路可以归为**一个根本错误**：试图在 Python 中模拟 Chrome 的行为，而不是直接在 Chrome 中执行。

具体来说，每个机制分别导致了什么偏差：

#### 机制 1+2+3：在 Python 中模拟 step 增量——根本不可能算对

机制 1（debug condition 累加函数源码长度）、机制 2（getter 劫持 step++）、机制 3（Proxy 拦截 step++）共同驱动 step 的增长。我花了大量时间在 Python 中手动累加这些增量，但每个都有偏差：

- **机制 1 的偏差**：debug condition 中调用其他被 instrument 的函数时，Chrome 会**抑制嵌套的 condition 评估**（见 [1.2 什么是 debug condition](#12-什么是-debug-condition调试条件)）。同一个函数在 debug condition 上下文中和在普通上下文中累加的 step 值不同，我测了几十次都有细微偏差
- **机制 2 的偏差**：getter 中 `step++` 返回旧值。当 step=0 时，`0 && 原始函数` = 0，getter 返回 0 而不是函数。check() 通过先执行 `[0].step`（触发 Proxy 使 step 变成 1）来避开这个边界。我在模拟时漏掉了这一步
- **机制 3 的偏差**：Proxy 插入原型链后，影响范围比想象的大得多。不只是数组操作，几乎所有属性查找都会触发。我在模拟时只给数组操作加了增量，导致 step 总是比实际少

**根本原因**：这三个机制是 Chrome 运行时行为，不是纯数学运算。你在 Python 中模拟，必然有遗漏和偏差。最终成功的做法是：在 Chrome 中注入代码，让 Chrome 自己驱动 step 的增长，一个都不漏。

#### 机制 4：Function tagged template——被障眼法骗了

看到第 255 行的 `while(true) debugger`，我认为这是 check() 的自检机制，花了很多时间研究怎么绕过。后来实际测试才发现：`Function\`...\`` 只是创建了一个函数对象但没有调用，自检代码**从未执行**（见 [3.5 机制四](#35-机制四check-第一行的-function-tagged-template)）。这行代码的真正作用是通过调用 `Function` 触发 debug condition 累加 step。`while(true) debugger` 纯粹是障眼法。

#### 机制 5：HTML 长度校验——试图修改文件

试图删掉 HTML 中的动画部分简化分析，删完后所有函数都触发断点（HTML 长度不再是 14347）。又试图补齐 HTML 长度，结果注释中的 Unicode 字符影响了其他逻辑。

**根本原因**：不要修改目标文件。即使你理解了检查的原理，修改文件也可能引入意想不到的副作用。

#### 机制 6：double() 障眼法——浪费时间分析一个空函数

看到 `window.step[U+FFA0] *= 2`，我认为 double() 会把 step 翻倍，花了大量时间模拟翻倍操作。后来用 `toString()` 检查才发现 `Function.call` + tagged template 创建的是空函数体（见 [3.7 机制六](#37-机制六double-障眼法)），double() 调用后什么都不做。浪费了一天。

#### 机制 7：U+FFA0 隐藏标识符——混淆了多个变量

把 `window.step[U+FFA0] *= 2` 当成了 `window.step *= 2`；把 `window.cﾠ`（anti() 设置的布尔值）和 `window.c`（`<meta id="c">` 的 DOM 元素）混为一谈。这些变量名只差一个不可见字符，肉眼看不出，JavaScript 引擎却严格区分。

#### 机制 8：tagged template 隐式 ROT13——20+ 个版本全错的元凶

第 262 行 `let pool = ﾠ\`...\`;` 看起来像普通字符串赋值，实际上 `ﾠ`（U+FFA0）是 ROT13 函数名，作为 tagged template 的标签函数在隐式调用。遗漏了这步 ROT13 后，pool 中的字符全部算错，所有 flag 都包含非法字符。详见 [4.3 最大的错误](#43-最大的错误误删-rot13-步骤)。

#### 复盘总结：一周的弯路可以归纳为两句话

1. **试图绕过运行环境，而不是在运行环境中工作。** debug condition、Proxy、getter 的 step 增量都依赖 Chrome 的运行时行为。在 Python 中模拟这些行为，即使差一个 step，flag 就完全错误。最终成功的做法是：在 Chrome 中注入代码，让 Chrome 自己驱动 step 增长，我只负责输入和输出。

2. **被障眼法牵着鼻子走。** double() 的"翻倍"、自检的"必须绕过"、隐藏标识符的"混淆变量名"——这些设计都是为了消耗你的注意力。真正决定 flag 正确性的只有两件事：pool 的正确计算（ROT13+ROT47）和 step 的正确累加（让 Chrome 自己做）。其余都是噪音。

## 第五章：完整攻击复现

### 5.1 自动化脚本（Python + Playwright）

以下脚本会自动打开 Chrome、执行 anti(debug) 和 unlock()，并保持 Chrome 打开 60 秒让你看到 alert 弹框：

```python
#!/usr/bin/env python3
"""
JS Safe 6.0 自动化解题脚本
依赖: pip install playwright && playwright install chromium
"""
from playwright.sync_api import sync_playwright
import time

HTML_URL = "file:///你的路径/js_safe_6.html"
FLAG = "CTF{1M_4_C7F_p14y32_4N71_d38U9_721cK5_d0n7_w02K_0n_m3}"

alert_text = [None]

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,  # 显示浏览器窗口
        args=['--auto-open-devtools-for-tabs']
    )
    context = browser.new_context()
    page = context.new_page()

    def on_dialog(dialog):
        alert_text[0] = dialog.message
        print(f"*** ALERT: [{dialog.message}] ***")
        time.sleep(15)  # 让你看到弹框 15 秒
        dialog.accept()
    page.on("dialog", on_dialog)

    page.goto(HTML_URL, timeout=30000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(5)

    # 获取 CDP session
    cdp = context.new_cdp_session(page)
    
    # 启用 Debugger 并自动 resume
    cdp.send("Debugger.enable", {})
    def on_paused(params):
        try: cdp.send("Debugger.resume", {})
        except: pass
    cdp.on("Debugger.paused", on_paused)

    # 第一步：anti(debug)
    cdp.send("Runtime.evaluate", {
        "expression": "anti(debug)",
        "returnByValue": True,
        "includeCommandLineAPI": True,  # 提供 debug() 函数
        "timeout": 30000,
    })

    # 第二步：unlock(flag)
    cdp.send("Runtime.evaluate", {
        "expression": f'unlock("{FLAG}")',
        "returnByValue": True,
        "includeCommandLineAPI": True,
        "timeout": 60000,
    })

    time.sleep(5)
    print(f"Flag: {FLAG}")
    print(f"Alert: {alert_text[0]}")
    
    time.sleep(60)  # 保持 Chrome 打开
    browser.close()
```

### 5.2 手动验证步骤

如果你想手动验证：

1. 用 Chrome 打开 `js_safe_6.html`
2. 按 F12 打开 DevTools
3. 在 Console 中输入：
   ```javascript
   anti(debug);
   ```
4. 等待命令执行完成（Console 返回 undefined）
5. 在 Console 中输入：
   ```javascript
   unlock("CTF{1M_4_C7F_p14y32_4N71_d38U9_721cK5_d0n7_w02K_0n_m3}");
   ```
6. 看到 alert 弹框显示 "JS Safe opened! Content:"

---

## 第六章：如何防御

这道题是一个 CTF 逆向题，但从防御角度可以学到：

| 防御点 | 本题的弱点 | 改进建议 |
|--------|-----------|---------|
| 客户端校验 | check() 在浏览器中运行，所有逻辑可被逆向 | 敏感校验放在服务端 |
| 代码混淆 | U+FFA0 和 tagged template 只增加了阅读难度 | 使用专业混淆器（如 javascript-obfuscator） |
| 反调试 | debug condition + step 计数器可被正向模拟 | 结合服务端验证，不依赖纯客户端反调试 |
| 密钥存储 | flag 直接硬编码在字符池中 | 密钥不应出现在客户端代码中 |
| 算法强度 | 线性同余生成器（LCG）是可预测的伪随机 | 使用密码学安全的随机数生成器 |

**核心教训**：JavaScript 运行在客户端，所有代码对用户可见。无论使用多少混淆和反调试技术，只要攻击者有足够时间分析，就一定能逆向出逻辑。**真正的安全依赖于服务端验证，而不是客户端的隐藏。**

---

## 第七章：总结

### Flag

```
CTF{1M_4_C7F_p14y32_4N71_d38U9_721cK5_d0n7_w02K_0n_m3}
```

解码含义：**"I'M A CTF PLAYER, ANTI DEBUG TRACKS DON'T WORK ON ME"**（我是 CTF 选手，反调试追踪对我没用）

### 攻击链回顾

```
阅读源码 → 识别反调试机制 → 识别 U+FFA0 隐藏标识符 → 
识别 tagged template 隐式 ROT13 → 计算 pool (ROT13+ROT47) →
理解 step 计数器机制 → 正向模拟 check() while 循环 → 
计算正确 flag → 在 Chrome 中验证
```

### 关键洞察

1. **"反调试"机制不是障碍，而是算法的一部分**。step 计数器决定了 flag 的每个字符从 pool 的哪个位置取。绕过反调试反而会导致错误的 step 值。

2. **tagged template 是最隐蔽的 trick**。`ﾠ\`...\`` 看起来像普通赋值，实际上暗中了 ROT13 变换。一旦遗漏这一步，后面所有的计算都会产生包含非法字符的 flag。

3. **最简单的方式往往是最正确的**。最终成功的版本（v333）只做了两件事：`anti(debug)` 和 `unlock(flag)`。之前所有复杂的绕过、模拟、override 都是多余的。

### 工具链

| 工具 | 用途 |
|------|------|
| Chrome DevTools | 手动调试和验证 |
| Playwright | 浏览器自动化（Python） |
| CDP (Chrome DevTools Protocol) | 远程执行 JavaScript、控制调试器 |
| Python | 编写自动化脚本 |
| VS Code / 编辑器 | 静态分析源码 |

### 失败教训

| 错误 | 影响 | 教训 |
|------|------|------|
| 遗漏 tagged template 的 ROT13 | 20+ 个版本全部算错 flag | 仔细检查每一行代码的语法含义 |
| 清除 intervals | 改变了 step 初始值，check 无法通过 | 不要做多余操作，先试最简单的方式 |
| 过度关注 step delta 精度 | 忽略了 pool 计算的正确性 | 先验证基础假设，再优化细节 |
| 试图绕过反调试 | 破坏运行环境 | 理解机制比绕过机制更重要 |

---

## 第八章：人类方案 vs AI 方案

这道题有两个解题者：一个人类和一个 AI。人类看完源码后，只改了 3 处就解出来了。AI 写了 300+ 个版本的脚本，花了一周。这一章记录人类的思路、AI 的问题、以及差距为什么这么大。

### 8.1 人类的思路：废掉防线，改代码，拿答案

人类的思路是一条清晰的"废掉防线 → 改代码 → 拿结果"的链条。不需要理解算法怎么计算，不需要理解每个机制的具体原理。只需要识别出哪些是"防线"（阻止你改代码的东西），把它们废掉就行。

#### 第一步：废掉 HTML 长度校验

看源码发现改 HTML 文件会触发断点（第 285 行的 `document.documentElement.outerHTML.length !== 14347`）。这是反分析机制——它阻止你修改源码。

既然是反分析机制，废掉就行。`document.documentElement.outerHTML.length` 这个取值过程里可能有我无法预知的 Hook 点（debug condition 在每次函数调用时都会执行），所以取值我不改，但我把判断结果废掉——让它永远返回 `false`：

```javascript
// 原始：
debug(f, "document.documentElement.outerHTML.length !== 14347");

// 改为：照常取值，但最后返回 false
debug(f, "const xsfksf = document.documentElement.outerHTML.length !== 14347; false");
```

取值过程保留（避免踩到未知的 Hook 点），但判断结果被 `false` 覆盖，断点永远不会触发。

#### 第二步：废掉 CSP

改完代码刷新页面，报错。这是 `Content-Security-Policy`（CSP）在拦截。

##### 什么是 CSP？

CSP（Content Security Policy，内容安全策略）是浏览器的一种安全机制，由网页通过 HTTP 头或 `<meta>` 标签声明。它告诉浏览器"这个页面允许执行哪些脚本、加载哪些资源"。

这道题的 CSP（第 7 行）：

```html
<meta http-equiv="Content-Security-Policy" id="c"
      content="script-src 'sha256-P8ko...' 'sha256-eDP6...' 'unsafe-eval'">
```

`script-src` 控制页面允许执行哪些 JavaScript。这里有三个规则：

| 规则 | 含义 |
|------|------|
| `'sha256-P8ko...'` | 只允许执行哈希值匹配的内联脚本（第一个 `<script>` 块） |
| `'sha256-eDP6...'` | 只允许执行哈希值匹配的内联脚本（第二个 `<script>` 块） |
| `'unsafe-eval'` | 允许使用 `eval()`（题目需要，因为源码里有 `Function()` 构造器） |

**关键点**：`'sha256-...'` 是脚本内容的哈希值。如果修改了脚本内容（哪怕改一个字符），哈希值就变了，浏览器就会拒绝执行这个脚本。

这就是为什么改了 HTML 后页面报错——脚本内容的哈希和 CSP 声明的不匹配了。

**解决方法**：直接把 CSP 的 `content` 属性清空：

```html
<!-- 原始 -->
<meta http-equiv="Content-Security-Policy" id="c"
      content="script-src 'sha256-...' 'sha256-...' 'unsafe-eval'">

<!-- 改为：去掉 content 属性里的限制 -->
<meta http-equiv="Content-Security-Policy" id="c">
```

没有 `script-src` 限制，浏览器就不检查脚本哈希，随便改都行。又一道防线被废掉了。

#### 第三步：废掉 flag 对比

现在代码可以随便改了。看 check() 的核心逻辑：一个 while 循环，用 step 计数器从 pool 里按顺序取字符，和 flag 对比。取对了继续，取错了死循环。

**我不需要知道算法到底怎么计算，我只需要答案。** 所以把判断条件依然执行（保留 `flag[0] == pool[j % pool.length]` 这行代码，让它的副作用正常发生），但不采纳判断结果——if 条件只保留 `step < 1000000`：

```javascript
// 原始：
if (flag[0] == pool[j % pool.length] && (window.step < 1000000)) {

// 改为：判断照常执行（表达式语句，结果丢弃），但 if 不采纳
flag[0] == pool[j % pool.length];
if (  (window.step < 1000000))  {
```

这样循环体里 `shift()`、`splice()`、`renderFrame()`、`double()` 全部保留，step 增长路径完全不变。49 轮后 pool 和 flag 都清空，`success = true`。

#### 第四步：把 flag 弹出来

在 unlock() 的 alert 里加上 `window.flag`，就能在弹框里看到结果：

```javascript
// 原始：
alert("JS Safe opened! Content:" + decrypted);

// 改为：
alert("JS Safe opened! Content:" + decrypted + ",FLAG=" + window.flag);
```

#### 完整改动汇总

| # | 位置 | 改动 | 目的 |
|---|------|------|------|
| 1 | 第 7 行 | CSP 去掉 `content` 里的 `script-src` | 允许修改后的脚本执行 |
| 2 | 第 286 行 | debug condition 最后加 `; false` | HTML 长度校验永远不触发 |
| 3 | 第 267 行 | 把对比从 if 条件拆出来变成独立语句 | 废掉 flag 验证，但保留所有副作用 |
| 4 | 第 319 行 | alert 里加 `window.flag` | 把结果弹出来 |

#### 使用方法

```
1. 用 Chrome 打开修改后的页面（examples/web/js_safe_6_副本2.html）
2. 按 F12 打开 DevTools
3. 在 Console 中输入: anti(debug);
4. 在 Console 中输入: unlock("CTF{aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}");
5. 弹出 alert，显示存储的密文和输入的密码
```

密码可以是任意符合正则 `/^CTF{([0-9a-zA-Z_@!?-]+)}$/` 的字符串，长度够 49 个字符就行。

### 8.2 AI 的方案：理解机制，正向计算

AI 的方案完全不同。AI 没有改 HTML 文件，而是：

1. 阅读源码，识别 8 个反调试机制
2. 手动计算 pool（ROT13 + ROT47 解码）
3. 通过 Playwright + CDP 在 Chrome 中注入代码
4. 注入代码复用 check() 的算法，直接从 pool 取字符拼成 flag
5. 用 `unlock("正确的flag")` 验证

最终成功的脚本（v333）只有两步：`anti(debug)` 和 `unlock(flag)`。

### 8.3 两种方案的对比

| 维度 | 人类的方案 | AI 的方案 |
|------|-----------|----------|
| 核心思路 | 废掉防线 → 改代码 → 拿结果 | 理解机制 → 正向计算 → 验证结果 |
| 改动量 | 3 处改 HTML | 不改 HTML，通过 CDP 注入代码 |
| 是否需要理解 pool 编码 | 不需要 | 需要理解 ROT13 + ROT47 |
| 是否需要理解 step 机制 | 不需要（保留所有机制，让它们自己跑） | 需要理解 step 如何累加 |
| 是否需要 Playwright/CDP | 不需要，手动在 Console 操作 | 需要，用 Python 脚本自动化 |
| 是否需要理解每个反调试机制 | 不需要，识别出"这是防线"然后废掉就行 | 需要逐一分析每个机制的作用 |
| 耗时 | 看完源码后几分钟 | 一周，300+ 个版本的脚本 |
| 拿到的结果 | 绕过验证，用任意密码解密密文 | 计算出正确的 flag |

### 8.4 为什么差距这么大

#### 人类的思维方式：试探 → 遇到问题 → 解决问题 → 继续试探

人类不是先做完整分析再动手。人类的思维方式是**不断试探和突破过程中的关键点**：先动手试试，遇到问题就停下来解决，解决了继续往前走，再遇到问题再解决，不断循环，最终一定能找到答案。

以这道题为例，人类实际的解题过程是这样的：

```
第一轮试探：随便输入一个 flag 试试
  → 发现改了 HTML 代码后，执行到某个地方被断点断下来了
  → 聚焦分析：为什么会断下来？
  → 看到第 285 行 debug condition 检查 HTML 长度
  → 解决：让 condition 返回 false，断点不触发
  → 继续试探

第二轮试探：改完代码刷新页面
  → 发现页面报错，脚本没执行
  → 聚焦分析：为什么没执行？
  → 看到 CSP 的 script-src 哈希校验，改了代码哈希就对不上了
  → 解决：去掉 CSP 的 script-src 限制
  → 继续试探

第三轮试探：现在代码可以随便改了
  → 改掉 check() 里的 flag 对比，让循环跑满 49 轮
  → 解决：对比从 if 条件拆出来变成独立语句，if 只保留 step < 1000000
  → 继续试探

第四轮试探：跑一下看看结果
  → 结果在变量里，看不到
  → 解决：在 alert 里加上 window.flag
  → 拿到答案
```

这个循环的关键特征：

1. **视野始终聚焦**。人类不会漫无目的地分析所有 8 个机制。每一轮只关注眼前遇到的那一个问题——为什么断了？为什么报错？为什么看不到结果？问题和目标是明确的，分析范围是收敛的。

2. **根据反应做决策**。人类不是先想好完整方案再动手，而是先试探（随便输个 flag、改一下代码），看有什么反应，然后根据反应决定下一步。遇到断点就分析断点，遇到报错就分析报错，每一步都有具体的线索。

3. **用上下文和知识找原因**。遇到问题后，人类会在目标上下文（当前代码、当前执行流程）和自己的知识（debug condition 的原理、CSP 的机制）之间找原因。不需要完整理解所有代码，只需要理解眼前这个问题的因果链。

4. **解决完就继续，不回头看**。每个问题解决后，人类不会停下来验证"我是否理解了整个系统"，而是直接继续试探，看下一个问题是什么。

#### AI 的思维方式：先完整分析，再动手

AI 的思维方式完全不同。AI 倾向于先做完整分析，理解所有机制，然后再动手实现：

```
AI 的过程：
1. 完整阅读源码 → 识别 8 个机制
2. 分析每个机制的原理（debug condition、Proxy、getter、tagged template...）
3. 试图理解 step 的完整增长路径
4. 试图在 Python 中重现 step 的增长
5. 发现算不对 → 回去重新分析
6. 发现 pool 算错了 → 回去重新分析
7. ... 重复 300+ 次
```

这个方式的问题：

1. **视野发散**。AI 试图同时理解所有 8 个机制，但其中 5 个（double 障眼法、Function 自检、U+FFA0 混淆、tagged template ROT13、HTML 长度校验）对"配出正确的 flag"没有帮助。人类不需要理解这些——它们是路上的干扰，不是必须解决的问题。

2. **没有利用试探的反馈**。AI 不去试探"改了代码会怎样"，而是试图在脑中推演出完整的结果。但 Chrome 的运行时行为（嵌套 debug condition 抑制、Proxy 拦截范围）太复杂，无法在脑中推演。人类直接在浏览器里试探，Chrome 的反馈就是答案。

3. **追求理解而非追求结果**。AI 花了大量时间试图理解"step 为什么是这个值"，但人类的方案根本不需要知道 step 是多少——让机制照常运行，step 自然就对。

#### 根本差异

| 人类 | AI |
|------|-----|
| 先动手试探，遇到问题再分析 | 先完整分析，理解了再动手 |
| 视野聚焦：只看眼前的问题 | 视野发散：试图理解所有机制 |
| 根据反馈做决策（断点了？报错了？） | 根据推理做决策（应该是这样的...） |
| 不需要理解整个系统，只需要解决眼前的问题 | 试图理解整个系统后再行动 |
| 在正确的环境（浏览器）里试探 | 在错误的环境（Python）里推演 |
| 几分钟 | 一周 |

用修车来打比方：人类是**发动引擎，哪里响了修哪里，响了再修，最终车能跑**。AI 是**把整辆车拆成零件，研究每个零件的原理，然后在纸上模拟发动机运转，试图算出正确的转速**。人类的每一步都是有针对性的——响了我才去查那个部位，不响的部位不需要管。AI 则是不管响不响，先全部拆一遍。

讽刺的是，AI 的模拟推演看起来是在"绕过问题"——试图不碰真实环境就算出答案——结果反而把自己绕进去了。人类才是真正在"解决问题"——每一个障碍都是直接面对、直接解决、然后继续往前。
