# 技术选型决策树

> AI 编排器在需要实现算法、编写求解器、性能敏感计算时按需加载。

## 触发条件

- 需要实现加密/解密算法
- 需要编写暴力搜索或数学求解器
- 涉及大量数据处理或性能敏感计算
- 不确定使用 Python 还是 C/C++ 时

---

## 决策树

### 第一步：判断计算规模

| 估算单次计算耗时 | 预估迭代次数 | 总耗时估算 | 推荐 |
|-----------------|------------|-----------|------|
| < 0.01s | < 1000 | < 10s | Python |
| 0.01s - 1s | > 10000 | > 100s | **C/C++** |
| > 1s | 任意 | 任意 | **C/C++** |
| 不确定 | 未知 | 未知 | Python 原型 → 性能测试 → 必要时转 C |

### 第二步：选择技术

| 场景 | 首选技术 | 原因 | 备选 |
|------|---------|------|------|
| 计算密集型（暴力搜索、ECDLP、大数运算） | C/C++ | 10-100x 性能 | gmpy2 加速的 Python |
| 算法验证（确认加密是否标准实现） | Unicorn 模拟原函数 | 无需重实现 | Hook 读取 |
| 算法逆向（理解自定义变体） | 静态分析 + Hook | 需理解细节 | — |
| 少量计算（构造输入、格式转换） | Python | 够用 | — |
| 性能不确定时 | Python 原型 → 转 C | 渐进策略 | — |
| 需要调试运行时行为 | IDA 调试器 / Frida | 动态分析 | — |
| 大整数运算（密码学） | Python + gmpy2 | 开发快 | C + GMP |

### 第三步：验证选择

选择后回答以下问题：
1. 预估总耗时是否在 10 分钟以内？（是 → 继续；否 → 考虑升级技术栈）
2. 是否可以用 Unicorn 模拟替代手动重实现？（是 → 优先模拟）
3. Python 是否有现成库可用？（是 → 先用库验证，不要手写）

---

## C/C++ 编译流程

### Windows (MSVC)

使用 `detect_env.py` 检测到的 `vcvarsall.bat` 路径：

```bash
# 32 位目标（常见于逆向目标）
cmd /c "call "<vcvarsall_path>" x86 >nul 2>&1 && cl /O2 /Fe:<output.exe> <source.c>"

# 64 位目标
cmd /c "call "<vcvarsall_path>" x64 >nul 2>&1 && cl /O2 /Fe:<output.exe> <source.c>"
```

### Linux

```bash
gcc -O2 -o <output> <source.c> -lgmp   # 需要 GMP 时
gcc -O2 -o <output> <source.c>          # 不需要 GMP
```

### macOS

```bash
clang -O2 -o <output> <source.c>
```

---

## 渐进策略：Python 原型 → C 加速

当性能需求不明确时，推荐以下流程：

1. **Python 原型**：用 Python + gmpy2 快速实现，验证算法正确性
2. **性能测试**：用小规模数据测试，估算实际耗时
3. **判断**：如果 Python 够用（< 10 分钟），就不再优化
4. **转 C**：如果 Python 不够用，将核心循环转为 C，通过 subprocess 调用

### Python 调用 C 的模式

```python
import subprocess
result = subprocess.run(
    ["./solver", str(param1), str(param2)],
    capture_output=True, text=True, timeout=3600
)
output = result.stdout.strip()
```

### C 模板

```c
#include <stdio.h>
#include <stdlib.h>
// 按需添加: #include <gmp.h>

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <param1> <param2>\n", argv[0]);
        return 1;
    }
    // 核心计算逻辑
    // 结果输出到 stdout，方便 Python 捕获
    printf("%llu\n", result);
    return 0;
}
```

---

## 静态分析 vs 动态分析（主动决策）

> 不要等失败后才切换。在阶段 B 规划时就根据场景选择分析方式。

| 场景 | 首选方式 | 原因 | 何时切换 |
|------|---------|------|---------|
| 标准/已知加密算法 | 静态（识别常量） | 模式识别即可 | 常量不匹配 → 切 Unicorn 验证 |
| 自定义/变异加密 | 动态（Hook + 模拟） | 静态难以理解变体 | — |
| 大型模板库（CryptoPP 等） | 动态（调试器/Unicorn） | 模板展开后代码量大，静态分析不切实际 | — |
| 壳/保护 | 动态（OEP → dump） | 静态脱壳算法复杂度高 | — |
| 算法验证（输入→输出） | Unicorn 模拟 | 无需理解内部实现 | — |
| 保护机制分析 | 静态为主 | 需要理解每一步细节 | 静态看不懂 → 切动态观察运行行为 |

**决策规则**：如果静态分析在 15 分钟内无法定位关键逻辑 → 立即切动态。

---

## 并行计算策略

> 计算密集型任务可通过多线程/多进程并行加速。ECDLP 特定的并行实现细节见 `ecdlp-solving.md`。

### 线程数选择

| 场景 | 线程数 | 原因 |
|------|--------|------|
| ECDLP (64-bit) | `min(cpu_count, 16)` | 8 线程比单线程快 ~50x |
| 暴力搜索 | `cpu_count` | 线性加速，无锁竞争 |
| 内存密集型（哈希表查表） | `min(cpu_count, 4)` | 内存带宽瓶颈，更多线程无收益 |

### Distinguished Points (DP) 策略（通用）

**适用场景**: 多线程随机游走类算法（线程间不共享路径，只通过 DP 表碰撞）。

**核心机制**:
- 游走过程中，只有满足特定条件（如值的低 d bit 全零）的"特殊点"才被记录
- 多线程各自游走，记录的 DP 点写入共享哈希表
- 当两个不同路径到达同一点（DP 碰撞），即可求解

**DP mask 选择原则**:
- d 值决定 DP 概率 = 1/2^d
- d 小 → 记录频繁 → 表大但碰撞快
- d 大 → 记录稀疏 → 表小但碰撞慢
- 推荐: d ≈ 问题规模位数/2 - 4（如 64-bit 问题 → d=28）
- 可用内存 = `预计 DP 数量 × 每条目大小`，需提前估算

**DP 表实现模式**:
1. 共享哈希表（以 DP 值为 key）
2. 线程安全写入（`CRITICAL_SECTION` / `pthread_mutex`）
3. 新 DP 写入前检查是否已存在（碰撞检测）

### MSVC 多线程 API（Windows）

```c
#include <windows.h>

CRITICAL_SECTION cs;
InitializeCriticalSection(&cs);

// 创建线程
HANDLE hThread = CreateThread(NULL, 0, WorkerFunc, &arg, 0, NULL);

// 保护共享数据
EnterCriticalSection(&cs);
// ... 写 DP 表 ...
LeaveCriticalSection(&cs);

// 终止标志（原子操作）
volatile LONG g_found = 0;
InterlockedExchange(&g_found, 1);  // 设置标志
if (g_found) return;               // 检查标志

// 等待所有线程
WaitForMultipleObjects(nThreads, hThreads, TRUE, INFINITE);
```

**Linux 替代方案**: 用 `pthread` + `pthread_mutex_t`，详见 `ecdlp-solving.md` C 模板。

### Python 调用并行 C 程序模式

编译多线程 C 程序后，通过 subprocess 调用：

```python
import subprocess, os

# 线程数通过命令行参数传递
cpu_count = os.cpu_count() or 4
nthreads = min(cpu_count, 16)

result = subprocess.run(
    ["./solver", str(nthreads)],
    capture_output=True, text=True, timeout=3600  # 1小时超时
)

if result.returncode == 0 and "FOUND" in result.stdout:
    # 解析结果
    for line in result.stdout.strip().split("\n"):
        if line.startswith("FOUND"):
            print(f"求解成功: {line}")
else:
    print(f"求解失败: {result.stderr}")
```

**注意**：用户看到多个 C 进程或高 CPU 占用是正常的并行行为，不是资源泄漏。

---

## 常见误区

| 误区 | 正确做法 |
|------|---------|
| 用 Python 暴力搜索 64-bit 空间 | 必须用 C，Python 需要数百年 |
| 手动重实现标准算法 | 先用 Unicorn 模拟验证，再决定是否需要重实现 |
| 不做性能估算就开始编码 | 先用小规模数据测试，估算总耗时 |
| 纠结于语言选择不做实事 | Python 原型先行，验证正确后再优化 |

---

## 性能基准参考

| 操作 | Python | C/C++ | 加速比 |
|------|--------|-------|--------|
| ECDLP Pollard's rho (64-bit) | ~0.8M 步/s/core | ~50M 步/s/core | ~60x |
| 大数模幂 (1024-bit) | ~1000 次/s (gmpy2) | ~50000 次/s (GMP) | ~50x |
| AES 加密 | ~10 MB/s (pycryptodome) | ~1 GB/s (OpenSSL) | ~100x |
| 简单整数运算 | ~50M 次/s | ~2G 次/s | ~40x |
