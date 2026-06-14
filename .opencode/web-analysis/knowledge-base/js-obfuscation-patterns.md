# JavaScript 混淆模式识别与反混淆

> 分析 JS 逆向题/恶意脚本/混淆代码时使用。

---

## 1. 不可见 Unicode 字符混淆

### 场景

源码中存在不可见的 Unicode 字符，用于隐藏变量名或伪装代码结构。

### 识别方法

1. **编辑器可视化**：VS Code 中不可见字符会显示为黄框/彩色方块
2. **十六进制查看**：`xxd file.html | head -100` 可看到实际字节
3. **Python 检测脚本**：

```python
# 检测文件中的可疑 Unicode 字符
import re
with open("target.js", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        # U+FFA0 (韩文半角填充符) — 合法标识符字符，常用于隐藏变量名
        if "\uffa0" in line:
            print(f"Line {i}: U+FFA0 found (identifier char)")
        # U+2000-U+200A (各种空格变体) — 伪装成代码空格
        for ch in line:
            if "\u2000" <= ch <= "\u200a":
                print(f"Line {i}: U+{ord(ch):04X} found (invisible space)")
                break
```

### 关键 Unicode 类别

| 字符 | 码位 | Unicode 分类 | 能当变量名？ | 常见混淆用途 |
|------|------|-------------|------------|-------------|
| ﾠ | U+FFA0 | 韩文字母 (ID_Start + ID_Continue) | ✅ 能 | 隐藏变量名：`window.cﾠ` 看起来像 `window.c` |
|   | U+2002 | 空格类 (Zs) | ❌ 不能 | 伪装代码空格 |
|   | U+2003 | 空格类 (Zs) | ❌ 不能 | 伪装代码空格 |
|   | U+2005 | 空格类 (Zs) | ❌ 不能 | 伪装代码空格 |

### 反混淆方法

- 用 Python 脚本替换不可见字符为可见标记后重新阅读
- 在浏览器 Console 中用 `Object.getOwnPropertyNames(window)` 列出所有全局变量，发现隐藏变量名
- 搜索 `window[` + Unicode 转义序列（如 `window['\uFFA0']`）来定位隐藏变量的使用

### 常见陷阱

- `window.c`（无 U+FFA0）和 `window.cﾠ`（有 U+FFA0）是**两个完全不同的变量**
- 搜索 `window.c` 找不到 `window.cﾠ`
- 浏览器 Console 输出中不可见字符可能被省略，导致变量名看起来一样

---

## 2. Tagged Template 隐式函数调用

### 场景

代码中 `identifier\`string\`` 看起来像普通赋值，实际上 `identifier` 是一个函数名，作为 tagged template 的标签函数被隐式调用。

### 识别方法

1. **检查赋值语句的"变量名"**：如果 `=` 后面紧跟的标识符后接反引号，它可能是函数调用
2. **在浏览器中验证**：

```javascript
// 假设源码有: let pool = ﾠ`some_string`;
// 检查 ﾠ (U+FFA0) 是否是函数:
console.log(typeof window['\uFFA0']);  // "function" → tagged template 调用
```

### 工作原理

```javascript
// 普通模板字符串
let a = `hello`;           // a = "hello"

// Tagged template（标签模板）
function rot13(s) { /* ... */ }
let b = rot13`hello`;      // 等价于 rot13(["hello"])
// rot13 被调用！参数是包装成数组的模板字符串

// 当函数名是不可见字符时：
let c = ﾠ`hello`;          // 看起来像赋值，实际是 ﾠ(["hello"])
```

### 反混淆方法

- 找到每个 tagged template 标签函数的定义，理解它做什么变换
- 用 `window['\uXXXX']` 显式调用，验证函数行为
- 在 Chrome Console 中单步执行，观察 tagged template 的返回值

---

## 3. Function.call + Tagged Template 创建空函数

### 场景

代码中出现 `Function.call\`code\`` 或 `Function\`code\``，看似创建有副作用的函数，实际行为不同。

### 识别方法

检查 `Function` 前是否有 `.call`：

```javascript
// Function`code` — 创建函数体为 "code" 的函数
const f1 = Function`window.step *= 2`;   // f1 的函数体是 "window.step *= 2"

// Function.call`code` — tagged template 把参数当 thisArg
const f2 = Function.call`window.step *= 2`;  // 等价于 Function.call(["window.step *= 2"])
// call 的第一个参数是 thisArg（这里是数组），没有传给 Function 的参数
// 所以 f2 = Function()，函数体为空！调用 f2() 什么都不做
```

### 检查方法

```javascript
console.log(f1.toString());  // "function anonymous() { window.step *= 2 }"
console.log(f2.toString());  // "function anonymous() { }"  ← 空函数体
```

### 反混淆要点

- 这是**双层障眼法**：第一层是代码内容（可能引用了错误变量），第二层是函数体为空
- 不要假设 `Function.call\`...\`` 中的代码会执行——先验证函数体

---

## 4. 原型链 Proxy/getter 劫持

### 场景

代码通过 `Object.defineProperty` 或 `Proxy` 在原型链上插入拦截器，每次属性访问/函数调用都触发副作用。

### 识别方法

1. **搜索关键词**：`Object.defineProperty`、`Proxy`、`__proto__`、`getOwnPropertyDescriptors`
2. **检查原型链**：

```javascript
// 检查 Array.prototype 的属性是否被劫持
Object.getOwnPropertyDescriptor(Array.prototype, 'shift');
// 如果有 get 字段 → getter 劫持

// 检查原型链是否被插入 Proxy
Object.getPrototypeOf(Array.prototype);
// 如果输出包含 "Proxy" → 原型链被修改
```

### 工作原理

```javascript
// getter 劫持：每次访问 shift 属性都触发
Object.defineProperty(Array.prototype, 'shift', {
    get: function() { step++; return original_shift; }
});

// Proxy 拦截：在原型链上插入 Proxy
Array.prototype.__proto__ = new Proxy(Object.prototype, {
    get: (target, prop) => (step++, Reflect.get(target, prop)),
    apply: (fn, thisArg, args) => (step++, Reflect.apply(fn, thisArg, args))
});
```

### 反混淆方法

- 在拦截器之前保存原始方法的引用
- 用 `Reflect.apply` 绕过 getter 直接调用原始方法
- 理解拦截器的触发频率（每次属性访问 + 函数调用 = 2 次拦截器触发）

---

## 5. debug() 字符串参数中的隐藏代码

### 场景

`debug(func, "代码")` 的第二个参数是一个字符串，Chrome 会在每次调用 `func` 之前执行这个字符串里的代码。出题人利用此机制在字符串中藏入任意代码（如修改全局变量、调用函数、操作 DOM 等），返回值仅控制是否暂停。

### 识别方法

1. **搜索 `debug(` 或 `debug (`**：找到所有调用 `debug()` 函数的地方
2. **检查第二个参数的内容**：如果包含赋值、自增、函数调用、对象修改等操作（`step +=`、`window.x =`、`func()` 等），则存在隐藏逻辑
3. **注意**：`debug()` 只在 DevTools Console 环境中可用

### 关键行为

```javascript
debug(func, "window.step += 10; false");
// 每次 func 被调用时：
// 1. 执行第二个参数里的代码 "window.step += 10; false" → step 加 10
// 2. 返回 false → 不暂停，函数正常执行
// 字符串里的代码一定会执行，返回值只控制是否暂停
```

### 反混淆方法

- **如果需要字符串中代码产生的效果**：不能移除 debug 设置，必须让它们正常运行
- **如果不需要字符串中代码的效果**：移除断点 `undebug(func)`，或者直接不启用 `Debugger.enable`。**慎用**——移除后字符串里的代码不再执行，如果出题人把关键逻辑藏在里面，移除会导致程序行为异常或结果错误
- **自动化中**：CDP 需要 `Debugger.enable` 才会让第二个参数里的代码执行；不加则代码被跳过

---

## 6. 快速检测清单

遇到混淆 JS 代码时，按以下顺序快速排查：

```
1. 不可见字符检测
   ├── 用 xxd/Python 扫描文件中 U+FFA0 和 U+2000-U+200A
   └── 在浏览器中用 Object.getOwnPropertyNames() 列出隐藏变量

2. Tagged template 识别
   ├── 检查所有 `identifier`...`` 形式：identifier 是函数还是变量？
   └── 验证：typeof window['identifier 名称']

3. Function 构造器陷阱
   ├── 搜索 Function` 和 Function.call`
   └── 验证函数体：func.toString()

4. 原型链劫持检测
   ├── 搜索 Object.defineProperty 和 Proxy
   └── 验证：Object.getOwnPropertyDescriptor() 和 getPrototypeOf()

5. debug() 副作用检测
   ├── 搜索 `debug(` 或 `debug (` 调用
   └── 检查第二个参数的字符串是否包含赋值、自增、函数调用、对象修改等操作

6. 完整性校验
   ├── 检查是否有 HTML 长度/哈希校验
   └── 检查 CSP script-src 是否使用 sha256 脚本哈希（详见 $AGENT_DIR/knowledge-base/csp-bypass.md）
```
