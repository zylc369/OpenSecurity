# 需求: 浏览器自动化知识合并 + browser_cdp.py 跨平台启动脚本

## §1 背景与目标

### 来源痛点

Web 分析任务中"打开一个可调试的浏览器"这一操作反复试错（4 种方式尝试、进程被父 shell 会话连坐杀掉、平台专属命令不可移植），根因有二：

1. **知识重复且互斥**：`browser-debugging.md` §2 与 `platform-auth-strategy.md` §2 各写一份浏览器启动方式，其中 Popen 示例缺 `start_new_session`、"nohup 后台启动"会被会话中止连坐——两处技术描述均有缺陷，修改时只改一处漏另一处（前次进化的返工记录第 3 条已暴露过此重复，引用式收口不彻底）。
2. **无跨平台启动工具**：浏览器探测（本机 Chrome → Playwright 缓存）、进程脱离（POSIX/Windows）、CDP 就绪判定没有固化成脚本，每次临场决策。

附带缺口：
- 操作后确认策略缺失——曾按 toast 组件思维查找反馈，实际平台用页面文字反馈；toast 转瞬即逝不可作为确认手段。
- pickle 反序列化的指令级逃逸知识（OBJ 栈序、`__builtins__` dict、INT 构造禁字节等）未沉淀，同类题每次重新试错。

### 目标

1. `browser-debugging.md` + `platform-auth-strategy.md` **二合一**为新文档 `browser-automation.md`，浏览器启动技术实现只存在于该文档一处
2. 新增跨平台脚本 `web-analysis/scripts/browser_cdp.py`：三级 Chrome 探测 + 脱离进程启动 + 四段成功判定
3. 新文档含操作后确认方法论（持久信号优先原则）
4. `deserialization.md` §4 增补 pickle 指令级逃逸知识
5. 消费方引用全量更新，旧文件删除，全库零残留

## §2 技术方案

### 2.1 新文档 `web-analysis/knowledge-base/browser-automation.md`

```
# 浏览器自动化 — 启动 / 登录 / 接管 / 确认

## 1. 浏览器启动（技术唯一权威处）
   1.1 启动铁律: 需要有界面浏览器（用户介入/登录后接管）时必须用 browser_cdp.py，
       禁止 Playwright 直接 launch 后等待用户、禁止平台专属命令（open -na 等）临场发挥
   1.2 browser_cdp.py 用法: 子命令 start/probe、参数、输出语义
   1.3 内部机制（供无脚本环境参考的原理描述）:
       - 三级探测链: --browser 参数/env 覆盖 → 平台路径探测 → Playwright 缓存目录 glob
       - 脱离进程: POSIX start_new_session=True; Windows DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP
       - 四段成功判定: 端口预探测(复用) → poll() 即死检测(stderr 落盘) →
         轮询 /json/version → 超时诊断(多为 user-data-dir 与已有实例冲突)
   1.4 执行模式选型: A(Playwright 直接启动) vs B(独立进程 + CDP 接管)，选型规则，
       B 的启动一律走 browser_cdp.py（本文不重复命令）
## 2. 登录决策树（原 platform-auth-strategy §1 原样迁入）
## 3. 人机验证: 两类机制（原 §3 原样迁入）
## 4. 硬信号清单（原 §4 原样迁入）
## 5. CDP 核心 API（原 browser-debugging §1 原样迁入）
## 6. debug() API 和 debug condition（原 §3 原样迁入）
## 7. 常见陷阱（原 §4 四条 + 新增两条）
   7.5 接管期间用户关闭页面 → TargetClosedError，catch 后 ctx.new_page() 重开，不中断流程
   7.6 connect_over_cdp 后禁止 browser.close()（会关掉用户的浏览器），
       退出 with 块即自动断开；persistent_context 的 close 仅在确认无人接管时使用
## 8. 操作后确认方法论（新增）
   确认优先级: 持久信号优先于瞬态信号
   1) 提交动作前挂 page.on("response") 监听（零成本，响应体最权威）
   2) 提交后读页面 DOM 文字/状态标志（刷新后仍存在; DOM 文本或截图+OCR 均可）
   3) 禁止把 toast 作为确认手段（瞬态，轮询时机不可控）
   4) 页面无反馈 → CDP 提 cookie 直调 API，按响应语义判断
      （重复提交返回 already-solved 类错误 = 先前提交成功的证据）
   API 直调修正链: 401 → 补 Origin/Referer/Cookie → 400 → 读错误体中参数
   schema 提示（tRPC/zod 系错误体直接列出缺失字段名与 path）改参数 → 成功
```

### 2.2 脚本 `web-analysis/scripts/browser_cdp.py`

```python
# CLI 结构
browser_cdp.py start [--url URL] [--port 9222] [--profile DIR] [--browser PATH]
browser_cdp.py probe [--port 9222]

# 核心数据结构（规则 9 强类型）
@dataclass
class ChromeTarget:
    path: str          # 可执行文件绝对路径
    source: str        # "explicit" | "system" | "playwright-cache"
    platform: str      # "darwin" | "win32" | "linux"

# 三级探测链
1. --browser 参数 或 env BROWSER_CDP_CHROME     → explicit
2. 平台路径:
   darwin:  /Applications/Google Chrome.app/..., Google Chrome Beta.app
   win32:   Program Files / Program Files (x86) / LocalAppData 下 chrome.exe
   linux:   shutil.which("google-chrome"|"chromium"|"chromium-browser")
                                                     → system
3. Playwright 缓存目录 glob:
   darwin:  ~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/...
   linux:   ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome
   win32:   %LOCALAPPDATA%/ms-playwright/chromium-*/chrome-win/chrome.exe
                                                     → playwright-cache
全无 → stderr 报错 + 提示 python -m playwright install chromium，退出码 2

# 启动（脱离进程）
posix:   subprocess.Popen(args, start_new_session=True,
                          stdout=stderr_tmp_file, stderr=stderr_tmp_file)
win32:   subprocess.Popen(args, creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP, ...)
args 固定含: --remote-debugging-port=<port> --user-data-dir=<profile>
             --no-first-run --no-default-browser-check
profile 默认: web-analysis/.browser-profiles/<timestamp>（每次独立目录防实例冲突;
             跨次复用登录态用 --profile 显式指定固定目录）

# 四段成功判定
1. 启动前 GET http://127.0.0.1:<port>/json/version 成功 → 输出"复用现有实例"，退出码 0
2. 启动后 1s: proc.poll() 非 None → 读 stderr_tmp_file 报错，退出码 3
3. 轮询 /json/version（最长 15s）: 200 且 JSON 含 Browser 字段
   → stdout 输出: 浏览器版本 / CDP 端点 / profile 路径 / 接管示例命令，退出码 0
4. 超时: 进程活但端口不通 → 报告 user-data-dir 冲突可能，退出码 4

# probe 子命令: 仅做判定 1，输出 JSON（{"reachable": bool, "browser": str|null}）
```

### 2.3 消费方引用更新

| 文件 | 位置 | 改动 |
|------|------|------|
| `agents/web-analysis.md` | L105 | 策略引用改指 `browser-automation.md`；追加铁律一句: 有界面浏览器必须经 `$AGENT_DIR/scripts/browser_cdp.py` 启动 |
| `agents/web-analysis.md` | L168-169 | 索引两行合并为一行 `browser-automation.md` |
| `web-analysis/knowledge-base/client-side-attacks.md` | L212 | 引用改为 `browser-automation.md` |
| 旧 `browser-debugging.md`、`platform-auth-strategy.md` | — | 删除（内容已迁移） |

### 2.4 `deserialization.md` §4 Python 节增补

按"防御 → 原语"组织，零来源叙事：

```
### 受限 Unpickler 的指令级逃逸
- 禁 REDUCE → OBJ 指令（opcode 'o'）:
  栈序 MARK, callable（紧贴 MARK 之上）, args..., 'o' → callable(*args)
  （误序症状: 'str' object is not callable / no MARK exists on stack）
- 白名单 find_class → find_class("collections", "__builtins__"):
  非主模块的 __builtins__ 即 builtins.__dict__（普通 dict），配合
  collections._itemgetter（operator.itemgetter 类）下标取出 bytes/list/open/print
- 禁字节构造 → INT 指令: 被禁字节值用十进制 ASCII 表示（"I46\n" 表 0x2E），
  bytes(int_list) 服务端拼路径; SHORT_BINUNICODE 不能含禁子串（如 flag/os/import）
- 禁 STOP（0x2E）→ 截断流: 指令顺序执行完后流截断异常被 except 吞掉，不写 STOP
- itemgetter=下标 / attrgetter=属性，二者不通用; itemgetter("name") 构造后
  必须再调用一次 getter(bdict) 才拿到目标对象
- Python 3.12 collections 可用引用: _itemgetter/_sys/_collections_abc 存在;
  _operator/_heapq/_types 不存在
- 读文件免 read 属性访问: list(open(path)) 直接取行列表
### 调试法: 目标服务吞异常时
本地起同款环境（docker compose 附件）+ 不吞异常的复现脚本（traceback 写 stderr、
find_class 加打印探针）定位断链，再打远程
```

## §3 实现规范

- 文件位置: 脚本 `web-analysis/scripts/`，知识 `web-analysis/knowledge-base/`，需求 `requirements/evolve/`
- 依赖方向: browser_cdp.py 仅用标准库（subprocess/urllib/glob/os/sys/platform/dataclass/argparse/time/tempfile），不依赖 playwright 运行时（缓存目录 glob 而非 API）
- 知识编写遵守 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md` 与规则 8.0（零来源叙事）
- 旧文档内容迁移时逐节对照，不静默丢弃任何知识点

### §3.1 实施步骤拆分

```
步骤 1. 新增 browser_cdp.py
  - 文件: web-analysis/scripts/browser_cdp.py
  - 预估行数: ~170 行
  - 验证点: python -c compile 语法检查; --help 正常;
    probe 子命令对 127.0.0.1:9222 输出 JSON;
    start 子命令在本机实际启动（探测链命中 Playwright 缓存 Chrome）→
    CDP 就绪输出（含 PID）→ curl /json/version 交叉验证 → kill <PID> 清理
    并删除验证用 profile 目录
  - 实现约束: stdout 末行输出 {"pid": N, "port": P} 机器可读行供清理
  - 依赖: 无

步骤 2. 新建 browser-automation.md（合并 + 新增）
  - 文件: web-analysis/knowledge-base/browser-automation.md
  - 预估行数: ~300 行
  - 写法约束（规则 7）: 若单次内容超过 280 行，先 Write 前半（§1-§4），
    再 Edit 追加后半（§5-§8），禁止超限单次 Write
  - 验证点: 知识点覆盖对照表——旧 browser-debugging.md 的 §1/§2/§3/§4 与
    旧 platform-auth-strategy.md 的 §1/§2/§3/§4 每节内容均有对应去处;
    旧文档中的重复语句（如"启动/连接代码模板见""登录完成判定"各出现两次）
    合并为一处再迁入; 新增 §1.1-1.3/§7.5-7.6/§8 齐全;
    人工通读自包含; 无来源叙事词
  - 依赖: 步骤 1（引用脚本用法）

步骤 3. 消费方引用更新 + 旧文件删除
  - 文件: agents/web-analysis.md, client-side-attacks.md, 删 2 个旧知识文件
  - 预估行数: ~15 行改动
  - 验证点: grep -rn "browser-debugging|platform-auth-strategy" 全库
    （排除 requirements/ 归档）零残留; web-analysis.md 索引指向新文件
  - 依赖: 步骤 2

步骤 4. deserialization.md §4 增补
  - 文件: web-analysis/knowledge-base/deserialization.md
  - 预估行数: ~90 行
  - 验证点: §2.4 列出的 8 个知识点逐条在场; 无题目名/平台名/来源叙事;
    与既有"STOP 剥离链"条目无矛盾（互补: 彼为多 reduce 执行, 此为免 STOP）
  - 依赖: 无

步骤 5. web-analysis.md 铁律行 + Prompt 瘦身检查
  - 文件: agents/web-analysis.md
  - 预估行数: ~5 行
  - 验证点: 铁律行含脚本绝对路径形式 $AGENT_DIR/scripts/browser_cdp.py;
    展开行数 = 文件行数 - 7 占位符 + 各片段行数之和 < 450
  - 依赖: 步骤 3
```

## §4 验收标准

### 功能验收
1. `python browser_cdp.py start` 在本机（无系统 Chrome）自动落到 Playwright 缓存并启动成功，CDP 端口可访问，退出码 0
2. `probe` 子命令输出合法 JSON
3. 启动的浏览器进程在脚本退出后仍存活（脱离进程验证）
4. 端口已占用时 start 报"复用现有实例"而非再启动

### 回归验收
5. `browser-automation.md` 覆盖旧两文档全部知识点（对照表核验）
6. 全库 grep 旧文件名零残留（requirements/ 归档除外）
7. web-analysis.md 展开行数 < 450

### 架构验收
8. 浏览器启动技术实现全库唯一（browser-automation.md §1 + 脚本本身）
9. 脚本纯标准库、跨平台分支完整（darwin/win32/linux 三分支 + 探测三级）
10. 知识零来源叙事: grep 本次产出文件，叙事词限定为
    "复盘|实测|亲测|本次分析|验证过|CTF|赛|靶机|writeup" —— 技术名词
    （pickle/os 等模块与指令名）不计入

## §5 与现有需求文档的关系

- `progress-2026-09-12-platform-auth.md`（本日早些时候）: 创建了 platform-auth-strategy.md 并以"引用"方式收口与 browser-debugging.md 的重复——本需求将其**取代**（引用式收口失败，改为物理合并），该文档记录的历史返工不再适用于新结构
- 无其他冲突需求
