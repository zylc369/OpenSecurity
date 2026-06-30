# 跨平台框架逆向 — Flutter / React Native / Hermes

> 当目标应用使用跨平台框架（Flutter/RN/KMP/MAUI）时通过 Read 工具加载。
> 传统 DEX 反编译在这些框架上直接失效。Frida hook 见 `mobile-frida.md`。

## 触发条件

- APK 中 `lib/arm64-v8a/libapp.so` + `libflutter.so` → **Flutter**
- APK 中 `assets/index.android.bundle` 且文件头含 `Hermes` → **React Native (Hermes)**
- APK 中 `libmonodroid.so` → **.NET MAUI**（【待补充】）
- APK 中 Kotlin/Native 框架 → **KMP**（【待补充】）

## §1 框架指纹识别速查

| 特征文件 | 框架 | 静态工具 |
|---------|------|---------|
| `libapp.so` + `libflutter.so` | Flutter | blutter |
| `index.android.bundle`（Hermes 头） | React Native | hermes-dec |
| DEX + `SecShell`/`ijiami`/`libjiagu`/`libshell` | 加固的原生 | 先脱壳（frida-dexdump/FART/BlackDex）→ jadx |
| `libmonodroid.so` | .NET MAUI | 【待补充】 |

## §2 Flutter Dart AOT 逆向（blutter）

Flutter 将 Dart 编译为 AOT 机器码放入 `libapp.so`，符号被剥离。blutter 编译对应版本的 Dart VM 运行时，恢复类/函数/对象池。

**安装与使用**：
```bash
# 从 APK 提取 libapp.so 和 libflutter.so
python3 blutter.py lib/arm64-v8a out_dir
# 自动检测 Dart 版本并编译对应 VM
```

**产出**：
- `asm/*`：带符号的汇编（函数名恢复）
- `blutter_frida.js`：Frida hook 模板（可直接用于运行时拦截）
- `objs.txt` / `pp.txt`：对象池 dump

**局限**：**仅支持 Android arm64，iOS 不支持**。混淆样本仍缺失大量函数。

## §3 Flutter SSL Pinning Bypass（reFlutter）

reFlutter 用打过补丁的 Flutter 库重打包应用，patch `socket.cc`（流量监控/转发）和 `dart.cc`（打印类/函数）。

**使用**：
```bash
reflutter main.apk
# 对齐+签名（uber-apk-signer）
```

**重要变化（已验证）**：**Flutter 3.24.0+ 移除了硬编码的代理 IP/端口**，需直接在设备上配置代理：
```bash
adb shell "settings put global http_proxy <ip>:<port>"
```
Android 无需 root/装证书即可拦截。dump 文件在 `/data/data/<pkg>/dump.dart`。

**活跃维护**：Impact-I/reFlutter（原 ptswarm 版已于 2022-04 归档）。

## §4 React Native Hermes 字节码逆向（hermes-dec）

React Native 0.70+ 默认编译为 Hermes 字节码(HBC)。

**步骤**：
```bash
# 1. 解包
7z x app.apk
# 2. 确认 Hermes 字节码
file assets/index.android.bundle
# → "Hermes JavaScript bytecode, version 84"

# 3. 解析头
hbc-file-parser index.android.bundle

# 4. 反汇编 → .hasm
hbc-disassembler index.android.bundle output.hasm

# 5. 反编译 → 伪 JS
hbc-decompiler index.android.bundle output.js
```

**局限**：反编译输出非可执行 JS（不还原循环/条件结构），需结合人工分析。

**工具版本**：hermes-dec v0.1.5，支持 HBC bytecode v98。

## §5 反 Frida 绕过（frida-strace 观测法）

加固应用常检测 Frida（遍历 `/proc/self/maps`、线程名、端口）。Frida 17.8.0+ 新增 `frida-strace` 可观测应用发起的 syscall。

```bash
# 观测应用启动期的 syscall（openat 读 /proc、ptrace、kill 等）
frida-strace -U -f com.xxx

# 定位检测点后，针对性 hook
# Frida 17.x 支持自定义 redirect emitter 降低 hook 可预测性
# Frida 17.11.0+ 支持 ptrace-free 注入（走 /proc/$pid/mem），应对 ptrace 被占用
```

## §6 解题方法论

1. **指纹识别先行**：判断框架类型（见 §1 速查表）
2. **按框架选工具**：Flutter→blutter + reFlutter；RN→hermes-dec；原生→jadx
3. **流量优先**：能用 reFlutter/objection 抓流量解的题先走流量，避免硬刚 native
4. **反 Frida**：frida-strace 观测 syscall → 定位检测 → stealth hook
5. **Flutter 3.24+ 代理**：必须用设备级 `adb shell settings put global http_proxy`

## §7 工具速查

| 工具 | 用途 | 版本/状态 |
|------|------|----------|
| blutter | Flutter Dart AOT 符号恢复 | worawit/blutter, 2026-04 更新, 仅 arm64 |
| reFlutter | Flutter SSL pinning bypass + 流量 | Impact-I/reFlutter v3, 2026-06 活跃 |
| hermes-dec | RN Hermes 字节码反编译 | P1sec/hermes-dec v0.1.5, HBC v98 |
| Frida 17.x | 运行时 hook + frida-strace | 17.15.3, ptrace-free 注入 |
| jadx | DEX 反编译 | 1.5.5, 插件/映射/调用图 |

## §8 关联文件

- `$AGENT_DIR/knowledge-base/mobile-frida.md` — Frida hook 基础
- `$AGENT_DIR/knowledge-base/flutter-ssl-bypass.md` — Flutter SSL bypass 详情（如有）
- `$AGENT_DIR/knowledge-base/android-unpacking.md` — Android 脱壳
