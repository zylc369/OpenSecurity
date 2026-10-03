# 分析-RoboCall

> SunshineCTF robocall — 逆向（信息枚举类：栈布局导航 + 栈残留泄漏，无利用原语）
> 题面："Welcome to robocall! Let's see how nimbly you navigate this stack."

Files: docs/分析/二进制安全/分析-RoboCall/robocall

nc sunshinectf.games 26199

## Flag

```
sun{you_must_be_some_sort_of_nimble_space_navigator}
```

**已通过官方平台验证**（2026.sunshinectf.org，无头浏览器提交，API 返回 `status=correct`）。

- **44/52 字节为远程实证泄漏**（11 块 × 4 字节，栈残留打印原语，见下文）；其余 8 字节（块 6/9）经数学论证不可达，为语义推断
- `[24:28]` = `t_of`（"some sort of nimble"，英语惯用推断）
- `[36:40]` = `spac`（+e = "space"，太空/栈空间双关——与二进制内 "In Space No One Can Hear You Scream" 彩蛋及太阳系客服主题呼应）
- 教训记录：两个缺口技术上数学不可达（16 字节网格，见下文证明），只能语义推断；推断必须找验证渠道（平台提交）闭环，未验证的猜测不应交付

## 二进制侦察

```
Arch: amd64-64-little    RELRO: No RELRO    Stack: No canary
NX: enabled              PIE: enabled        Stripped: No
```

客服电话地狱模拟器：多层菜单（start_position → initial_call → other_inquiries → cancel_plan …），
全部 I/O 走 `raw_print` / `raw_readline` / `raw_parse_int` / `raw_print_int`，无 printf 无格式化串。
主输入 `42` 可关闭 `be_annoying` 延迟（否则每步 nanosleep 2s）。

## 核心机制

### 1. place_flag：flag 打散进栈残留

`main` 首先调用 `place_flag`：
- 从 flag.txt 读 ≤0x3c 字节到 `[rbp_pf-0x2060]`（**原始连续副本**）
- 清零 `[rbp_pf-0x2020, rbp_pf-0x20)`
- 按 `CHUNK_DEPTH[13]` 表把 flag 每４字节写到 `rbp_pf - 0x644 - d[i]`（d = 0x400,0x480,0x520,0x570,0x5a0,0x640,0x690,0x6c0,0x760,0x7b0,0x7e0,0x800,0x880）
- place_flag 返回后，这些块以**栈残留**形式留在 main 之下的死区

### 2. 泄漏原语：未初始化槽打印

`cancel_plan`（帧 0x430，正好罩住碎片区）的确认流程：

```
第一问 raw_readline(buf) → raw_parse_int(buf, &slot)   slot = [rbp_cp-0x204]
第二问 raw_readline(buf) → raw_parse_int(buf, &slot)
raw_print_int(slot)   ← 0x2f4b 唯一的动态打印
```

`raw_parse_int` 对**非数字输入直接返回、不写输出指针** → 两问均输入非数字（如 `z`）时，
打印的是 `slot` 的**进入本函数时的栈残留**。栈深合适时 = flag 碎片（小端 int）。

### 3. 栈深控制：菜单环

程序所有出口都 `call start_position`（函数永不返回，栈只增不减），
不同菜单回路形成精确的栈深增量（**均经 qemu+gdb 实测**）：

| 环 | 操作 | 增量 |
|---|---|---|
| scream | sp 菜单 3 → scale 1 | 0x120 |
| report | sp→1→2(report)→输一行 | 0x400 |
| tech | sp→1→4→2→login×3 | 0x410 |
| billing | sp→1→3→1/2→login×3+payment×4 | 0x430 |
| upgrade | sp→1→5→1→login×3 | 0x440 |
| swo | sp→1→6→3（hold 随机循环后退出）| 0x4C0 |
| cp 出口 | cancel_plan 任意退出 | 0x880 |
| cp 递归 | cancel 菜单 4 | 0x440/层 |

块 i 对齐条件：`Σ(环增量) == CHUNK_DEPTH[i]`（打印槽恰落在块首）。
副本 buf 的 off 窗口条件：`Σ = 0x1A1C - off`，且 `off ≡ 12 (mod 16)`。

### 4. 泄漏方案（每块一个连接）

| 目标 | 方案 Σ |
|---|---|
| 块0 (sun{) | report |
| 块1 (you_) | 4×scream |
| 块2 (must) | report+1×scream |
| 块3 (_be_) | report+tech+16×scream（buf off=12）|
| 块4 (some) | 5×scream |
| 块5 (_sor) | report+2×scream |
| 块7 (_nim) | 6×scream |
| 块8 (ble_) | report+3×scream |
| 块10 (e_na) | 7×scream |
| 块11 (viga) | report×2 |
| 块12 (tor}) | report+4×scream |

块 6/9（d=0x690/0x7B0）**数学不可达**：所有函数 `sub rsp` 均为 16 倍数且无额外 push，
全部环增量 ≡ 0 (mod 16) 的半群无法表示这两个值；buf 副本窗口也受 `off ≡ 12 (mod 16)` 限制。
16 字节相位网格是结构性边界（穷举验证见过程记录）。

## 远程泄漏结果（实证）

```
sun{ you_ must _be_ some _sor ???? _nim ble_ ???? e_na viga tor}
```

## 文件

- `solve.py`：全量泄漏自动化（`--remote` 打远程；本地模式挂载脚本同目录，需 `robocall` + `flag.txt` 同目录放置）
- `verify_flag.py`：平台候选验证（playwright 无头浏览器；`state.json` 缺失时用 `RC_USER`/`RC_PASS` 环境变量自动登录生成）
- `verify_win.png`：平台返回 `correct` 的截图存证
- 依赖：pwntools + playwright；本地测试用 `docker run -i ubuntu:22.04`
