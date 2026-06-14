# ECDLP 求解经验

> AI 编排器在遇到椭圆曲线离散对数问题 (ECDLP) 时按需加载。

## 触发条件

- 反编译代码中出现椭圆曲线点加/点乘运算
- 曲线阶 n 为已知素数
- 需要由公钥点反推私钥（或由部分信息反推标量）

---

## 算法选择

| 曲线位数 | 算法 | 预估耗时 | 内存 |
|---------|------|---------|------|
| ≤ 32 bit | 暴力枚举 | < 1s (C) | 极低 |
| 33-64 bit | **并行 Pollard's rho + DP** | 分钟级 (C, 8线程) | 极低+DP表 |
| 33-64 bit | Pollard's rho（单线程） | 分钟-小时级 (C) | 极低 |
| 33-64 bit | Baby-step Giant-step | 分钟级 (C) | O(√n) |
| > 64 bit | 并行 Pollard's rho + DP | 天-年级 | 极低+DP表 |
| > 128 bit | **不可行** | 理论上不可能 | — |

**首选**: 并行 Pollard's rho + DP（低内存、多线程加速、DP 碰撞检测）

---

## 强制规则

> **64-bit 以上曲线的 ECDLP → 必须用 C/C++ 实现**

Python Pollard's rho ~0.8M 步/s/core，C ~50M 步/s/core，差距 60x。
64-bit 曲线需要 ~2^32 步，Python 需要 ~90 分钟，C 需要 ~1.5 分钟。

### `__umul128` vs `uint128_t` (MSVC)

MSVC 不支持 `__int128`，替代方案：

| 方案 | 实现 | 性能 |
|------|------|------|
| `__umul128` + `_umul128` | intrinsics，需要 `<intrin.h>` | **最优** — 编译器直接生成 `mul` 指令 |
| `unsigned __int128` | GCC/Clang 原生支持 | **等价** — 同样生成单条 `mul` 指令 |
| 手写 64x64→128 拆分 | 用 32-bit 半字乘法模拟 | 慢 ~2-4x |

**MSVC 下推荐**：`#include <intrin.h>` 使用 `__umul128(a, b, &hi)`，性能与 GCC `__int128` 等价。

---

## 性能基准

| 实现 | 速度 | 适用场景 |
|------|------|---------|
| Python (纯) | ~0.1M 步/s/core | 仅用于 32-bit 以下曲线 |
| Python + gmpy2 | ~0.8M 步/s/core | 48-bit 以下曲线的原型验证 |
| C + 128-bit 整数 | ~50M 步/s/core | 64-bit 曲线的生产求解 |
| C + GMP | ~40M 步/s/core | 任意位数（但 GMP 开销略大） |

---

## 并行 Pollard's rho + Distinguished Points (DP)

> ECDLP 特定的并行实现细节。通用 DP 策略和线程数选择见 `technology-selection.md`。

### 核心思想

多个线程各自从独立随机起点出发，沿椭圆曲线随机游走。每个线程只记录"特殊点"（Distinguished Points）到共享 DP 表。当两个不同线程记录了相同的 DP 时（碰撞），即可求解离散对数。

### DP 策略

- **判定条件**: 点 P 的 x 坐标低 d bit 全零时记录 — `(P.x & DP_MASK) == 0`
- **DP mask 选择**: `d = 曲线位数/2 - 4`（如 64-bit 曲线 → d=28，DP_MASK=0xFFFFFFF）
  - d 太小 → DP 表太大（每几步就记录一次）
  - d 太大 → 碰撞太慢（很久才遇到 DP）
- **记录频率**: 约每 `2^d` 步记录一次 DP
- **DP 表大小**: 预期总步数 `√n`，除以 `2^d`，即 `√n / 2^d` 个条目

### 线程数选择

```
线程数 = min(CPU 核心数, 曲线位数 / 8, 16)
```

- 8 线程通常比单线程快 ~50x（实测: 40s vs ~33min）
- 超过 CPU 核心数无意义（反而变慢）
- 不超过 16（DP 表碰撞率下降）

### 碰撞检测

- 各线程的 DP 点写入**共享哈希表**（以点 x 坐标为 key）
- 新 DP 与已有 DP 比较 y 坐标：
  - y 相同 → 同一点，同一线程内的 Floyd 碰撞（无用，跳过）
  - y 不同 → 不同路径到达同一点（有效碰撞，可求解 k）
- 线程安全：`CRITICAL_SECTION`（Windows）或 `pthread_mutex`（Linux）保护 DP 表写入

### 终止检测

- 共享原子标志 `g_found`（`volatile int`）
- 任一线程找到有效碰撞后设置标志
- 其他线程每 1000 步检查一次标志，发现后退出

### 结果计算

碰撞发现后，由发现碰撞的线程计算 k：
1. 线程 A 记录: DP = a₁·G + b₁·target
2. 线程 B 记录: DP = a₂·G + b₂·target
3. 如果 DP 相同: (a₁-a₂)·G = (b₂-b₁)·target
4. k = (a₁-a₂) · (b₂-b₁)⁻¹ mod n

---

## Pollard's rho 算法模板

### Python 原型（用于验证正确性）

```python
def pollard_rho(G, n, target_x, curve_add, curve_mul):
    """Pollard's rho 求解 ECDLP: 找 k 使得 (k*G).x mod n == target_x"""
    from random import randint

    def step(P, a, b):
        partition = P[0] % 3
        if partition == 0:
            return curve_add(P, G), (a + 1) % n, b
        elif partition == 1:
            return curve_double(P), (2 * a) % n, (2 * b) % n
        else:
            return curve_add(P, target_point), a, (b + 1) % n

    tortoise = (curve_mul(randint(1, n-1), G), 0, 0)
    hare = step(*step(*tortoise))

    while tortoise[0] != hare[0]:
        tortoise = step(*tortoise)
        hare = step(*step(*hare))

    # 恢复 k
    # ...
```

### C 模板（并行 Pollard's rho + DP，生产用）

> 完整可编译模板。仿射坐标，MSVC 兼容（`__umul128`），跨平台（`#ifdef _WIN32`）。

```c
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <intrin.h>
#else
#include <pthread.h>
#endif

/* ===== 曲线参数（按目标修改）===== */
#define P_VAL 0xC564EEF070E69193ULL  /* 素数 p */
#define N_VAL 0xC564EEF19A080B07ULL  /* 阶 n */
#define A_VAL 0ULL                   /* 曲线参数 a */
#define B_VAL 0ULL                   /* 曲线参数 b */

/* DP 参数 */
#define DP_BITS  28                  /* d = 曲线位数/2 - 4 */
#define DP_MASK  ((1ULL << DP_BITS) - 1)
#define MAX_DP   (1 << 18)           /* DP 表最大条目数 */
#define MAX_THREADS 16

/* ===== 仿射坐标点 ===== */
typedef struct { uint64_t x, y; } Point;
typedef struct { uint64_t a, b; } Coeff;  /* 游走系数: P = a*G + b*T */

/* ===== 128-bit 模运算（MSVC 兼容）===== */
#ifdef _WIN32
/* ---- MSVC 路径: 用 _umul128 + _udiv128（MSVC 2019+）---- */

static uint64_t p_val = P_VAL;

static void barrett_init(void) {
    /* MSVC 下直接用 _udiv128 做 128-bit 除法，无需预计算 */
}

static inline uint64_t mod_mul(uint64_t a, uint64_t b) {
    uint64_t hi, lo;
    lo = _umul128(a, b, &hi);
    uint64_t rem;
    _udiv128(hi, lo, p_val, &rem);
    return rem;
}

#else
/* ---- GCC/Clang 路径: 使用 __int128 ---- */

static uint64_t p_val = P_VAL;

static void barrett_init(void) {
    /* GCC/Clang 下直接用 128-bit 取模，无需预计算 */
}

static inline uint64_t mod_mul(uint64_t a, uint64_t b) {
    return (uint64_t)((unsigned __int128)a * b % p_val);
}

#endif

/* 模加（处理 a+b 溢出 uint64_t 的情况，当 p > 2^63 时可能发生）*/
static inline uint64_t mod_add(uint64_t a, uint64_t b) {
    uint64_t s = a + b;
    if (s < a) {
        /* 发生回绕: 真实值 = s + 2^64，需要 mod p */
        /* s + (2^64 - p) 即可（因为 2^64 mod p = 2^64 - p*k，这里 p < 2^64 所以 k=1）*/
        s += (UINT64_MAX - p_val + 1);
    }
    return s >= p_val ? s - p_val : s;
}

/* 模减 */
static inline uint64_t mod_sub(uint64_t a, uint64_t b) {
    if (a >= b) return a - b;
    /* a < b: 结果 = a - b + p。用两次加法避免溢出: 先加 (p-b)，再处理可能的溢出 */
    uint64_t d = p_val - b;   /* d > 0，d <= p */
    uint64_t r = a + d;       /* 可能溢出: a+d <= (p-1)+p = 2p-1 */
    if (r < a) {
        /* 溢出: 真实值 = r + 2^64，结果 = r + 2^64 - p = r + (2^64 - p) */
        r += (UINT64_MAX - p_val + 1);
    }
    return r;  /* r < p（因为真实值 = a-b+p，0 < a-b+p < p）*/
}

/* 模逆（费马小定理: a^(p-2) mod p）*/
static uint64_t mod_inv_fermat(uint64_t a) {
    uint64_t result = 1, base = a, exp = p_val - 2;
    while (exp > 0) {
        if (exp & 1) result = mod_mul(result, base);
        base = mod_mul(base, base);
        exp >>= 1;
    }
    return result;
}

/* ===== mod_n 运算（标量运算用 n 做模数，独立于全局 p_val）===== */
#ifdef _WIN32
static inline uint64_t mod_mul_n(uint64_t a, uint64_t b) {
    uint64_t hi, lo;
    lo = _umul128(a, b, &hi);
    uint64_t rem;
    _udiv128(hi, lo, N_VAL, &rem);
    return rem;
}
#else
static inline uint64_t mod_mul_n(uint64_t a, uint64_t b) {
    return (uint64_t)((unsigned __int128)a * b % N_VAL);
}
#endif

static inline uint64_t mod_sub_n(uint64_t a, uint64_t b) {
    if (a >= b) return a - b;
    uint64_t d = N_VAL - b;
    uint64_t r = a + d;
    if (r < a) {
        r += (UINT64_MAX - N_VAL + 1);
    }
    return r;
}

static inline uint64_t mod_add_n(uint64_t a, uint64_t b) {
    uint64_t s = a + b;
    if (s < a) {
        s += (UINT64_MAX - N_VAL + 1);
    }
    return s >= N_VAL ? s - N_VAL : s;
}

static uint64_t mod_inv_n(uint64_t a) {
    uint64_t result = 1, base = a, exp = N_VAL - 2;
    while (exp > 0) {
        if (exp & 1) result = mod_mul_n(result, base);
        base = mod_mul_n(base, base);
        exp >>= 1;
    }
    return result;
}

/* ===== 椭圆曲线点运算（仿射坐标）===== */
static Point POINT_ZERO = {0, 0};  /* 表示无穷远点 */

static int is_zero(Point P) { return P.x == 0 && P.y == 0; }

static Point point_add(Point P, Point Q) {
    if (is_zero(P)) return Q;
    if (is_zero(Q)) return P;
    if (P.x == Q.x) {
        if (P.y != Q.y) return POINT_ZERO;  /* 互逆 */
        /* 点倍: 斜率 = (3*x^2 + a) / (2*y) */
        uint64_t num = mod_mul(3ULL, mod_mul(P.x, P.x));
        if (A_VAL) num = mod_add(num, A_VAL);
        uint64_t den = mod_mul(2ULL, P.y);
        uint64_t lambda = mod_mul(num, mod_inv_fermat(den));
        uint64_t rx = mod_sub(mod_mul(lambda, lambda), mod_add(P.x, Q.x));
        uint64_t ry = mod_sub(mod_mul(lambda, mod_sub(P.x, rx)), P.y);
        return (Point){rx, ry};
    }
    /* 点加: 斜率 = (Q.y - P.y) / (Q.x - P.x) */
    uint64_t lambda = mod_mul(mod_sub(Q.y, P.y), mod_inv_fermat(mod_sub(Q.x, P.x)));
    uint64_t rx = mod_sub(mod_mul(lambda, lambda), mod_add(P.x, Q.x));
    uint64_t ry = mod_sub(mod_mul(lambda, mod_sub(P.x, rx)), P.y);
    return (Point){rx, ry};
}

/* 点乘（双重-and-加）— 仅用于初始化随机起点 */
static Point point_mul(uint64_t k, Point P) {
    Point result = POINT_ZERO;
    while (k > 0) {
        if (k & 1) result = point_add(result, P);
        P = point_add(P, P);
        k >>= 1;
    }
    return result;
}

/* ===== DP 表 ===== */
typedef struct {
    uint64_t px, py;  /* DP 点坐标 */
    uint64_t a, b;    /* 游走系数 */
} DPEntry;

static DPEntry dp_table[MAX_DP];
static int dp_count = 0;
static volatile int g_found = 0;  /* 终止标志 */

#ifdef _WIN32
static CRITICAL_SECTION dp_lock;
#else
static pthread_mutex_t dp_lock = PTHREAD_MUTEX_INITIALIZER;
#endif

/* ===== 随机游走步进 ===== */
/* 分区函数: 按 x mod 3 分成 3 组 */
static void rho_step(Point *P, Coeff *c, Point G, Point T) {
    switch (P->x % 3) {
        case 0:  /* P = P + G, a += 1 */
            *P = point_add(*P, G);
            c->a = mod_add_n(c->a, 1ULL);
            break;
        case 1:  /* P = 2*P, a *= 2, b *= 2 */
            *P = point_add(*P, *P);
            c->a = mod_add_n(c->a, c->a);
            c->b = mod_add_n(c->b, c->b);
            break;
        default: /* P = P + T, b += 1 */
            *P = point_add(*P, T);
            c->b = mod_add_n(c->b, 1ULL);
            break;
    }
}

/* ===== 工作线程 ===== */
typedef struct {
    int thread_id;
    Point G, T;       /* G: 基点, T: 目标点 */
    uint64_t seed;
} ThreadArg;

#ifdef _WIN32
static DWORD WINAPI worker(LPVOID arg) {
#else
static void *worker(void *arg) {
#endif
    ThreadArg *ta = (ThreadArg *)arg;
    Point G = ta->G, T = ta->T;

    /* 随机起点: P = a0*G + b0*T（a0/b0 用不同种子偏移确保独立性）*/
    uint64_t seed = ta->seed;
    uint64_t a0 = (seed * 6364136223846793005ULL + 1442695040888963407ULL) % N_VAL | 1;
    uint64_t b0 = (seed * 6364136223846793005ULL + 0x5DEECE66DULL) % N_VAL | 1;
    Point P = point_add(point_mul(a0, G), point_mul(b0, T));
    Coeff c = {a0, b0};

    uint64_t steps = 0;
    while (!g_found && steps < (1ULL << 40)) {
        rho_step(&P, &c, G, T);
        steps++;

        /* DP 判定 */
        if ((P.x & DP_MASK) == 0 && !is_zero(P)) {
#ifdef _WIN32
            EnterCriticalSection(&dp_lock);
#else
            pthread_mutex_lock(&dp_lock);
#endif
            /* 检查碰撞 */
            for (int i = 0; i < dp_count; i++) {
                if (dp_table[i].px == P.x) {
                    if (dp_table[i].py == P.y) continue; /* 同一点，跳过 */
                    /* 有效碰撞! 计算 k（使用 mod_n 系列函数，不修改全局 p_val）*/
                    uint64_t da = mod_sub_n(c.a, dp_table[i].a);
                    uint64_t db = mod_sub_n(dp_table[i].b, c.b);
                    if (db == 0) continue;
                    uint64_t k = mod_mul_n(da, mod_inv_n(db));
                    printf("FOUND k=0x%llX steps=%llu thread=%d\n",
                           (unsigned long long)k, (unsigned long long)steps, ta->thread_id);
                    fflush(stdout);
                    g_found = 1;
#ifdef _WIN32
                    LeaveCriticalSection(&dp_lock);
#else
                    pthread_mutex_unlock(&dp_lock);
#endif
                    return 0;
                }
            }
            /* 无碰撞，记录 DP */
            if (dp_count < MAX_DP) {
                dp_table[dp_count++] = (DPEntry){P.x, P.y, c.a, c.b};
            }
#ifdef _WIN32
            LeaveCriticalSection(&dp_lock);
#else
            pthread_mutex_unlock(&dp_lock);
#endif
        }

        /* 定期检查终止标志 */
        if (steps % 10000 == 0 && g_found) break;
    }
    return 0;
}

/* ===== main ===== */
int main(int argc, char *argv[]) {
    int nthreads = 8;
    if (argc > 1) nthreads = atoi(argv[1]);
    if (nthreads < 1) nthreads = 1;
    if (nthreads > MAX_THREADS) nthreads = MAX_THREADS;

    barrett_init();
#ifdef _WIN32
    InitializeCriticalSection(&dp_lock);
#endif

    /* 基点和目标点（按目标修改）*/
    Point G = {/* G.x */ 0, /* G.y */ 0};
    Point T = {/* T.x */ 0, /* T.y */ 0};

    fprintf(stderr, "[*] ECDLP 并行求解: %d 线程, DP_BITS=%d\n", nthreads, DP_BITS);

#ifdef _WIN32
    HANDLE threads[MAX_THREADS];
    ThreadArg args[MAX_THREADS];
    for (int i = 0; i < nthreads; i++) {
        args[i] = (ThreadArg){i, G, T, (uint64_t)(i + 1) * 123456789ULL};
        threads[i] = CreateThread(NULL, 0, worker, &args[i], 0, NULL);
    }
    WaitForMultipleObjects(nthreads, threads, TRUE, INFINITE);
#else
    pthread_t threads[MAX_THREADS];
    ThreadArg args[MAX_THREADS];
    for (int i = 0; i < nthreads; i++) {
        args[i] = (ThreadArg){i, G, T, (uint64_t)(i + 1) * 123456789ULL};
        pthread_create(&threads[i], NULL, worker, &args[i]);
    }
    for (int i = 0; i < nthreads; i++) {
        pthread_join(threads[i], NULL);
    }
#endif

    if (!g_found) fprintf(stderr, "[!] 未找到解\n");
    return g_found ? 0 : 1;
}
```

**编译命令**:

```bash
# Windows (MSVC) — 32位目标
cmd /c "call "<vcvarsall_path>" x86 >nul 2>&1 && cl /O2 /Fe:solver.exe solver.c"

# Linux
gcc -O2 -pthread -o solver solver.c

# macOS
clang -O2 -o solver solver.c

# 运行（Python 调用）
result = subprocess.run(["./solver", "8"], capture_output=True, text=True, timeout=3600)
```

---

## 特殊约束：非标准 ECDSA

某些实现（如 CryptoPP）可能要求 r=1，而非标准 ECDSA 的 r∈[1,n-1]。

### r=1 约束

- **特征**: 验证函数中有类似 `Compare(r, Integer(1)) == 0` 的检查
- **含义**: 不是求解任意 k，而是要求 `(k·G).x mod n == 1`
- **求解方法**: ECDLP 目标从"任意 r"变为"r=1"，即找 k 使得 k·G 的 x 坐标 mod n 等于 1
- **验证**: 确认点 (1, y) 在曲线上且在子群中

### n > p 异常

某些库（如 CryptoPP）可能接受 n > p 的曲线参数，虽然这违反 Hasse's bound（`|n - p - 1| ≤ 2√p`）。

- **影响**: 标量运算 mod n 和坐标运算 mod p 的值域不同，计算时必须严格区分
- **对策**: 不要假设 n ≈ p，始终在标量运算中用 n、坐标运算中用 p

---

## 渐进策略

1. **Python 原型**（~30 分钟）
   - 用 gmpy2 实现曲线运算
   - 用小曲线（已知答案）验证正确性
   - 用目标曲线测试几步，确认算法无误

2. **性能估算**（~5 分钟）
   - Python 跑 1000 步计时
   - 估算总步数 = √n
   - 如果 Python 需要超过 30 分钟 → 转 C

3. **C 实现**（~60 分钟）
   - 复制 Python 的曲线参数
   - 用 128-bit 整数或 GMP 实现模运算
   - 编译优化：`/O2` (MSVC) 或 `-O2` (gcc/clang)
   - 通过 subprocess 从 Python 调用

4. **并行化决策**（在 C 单线程验证后）
   - 单线程 C 跑 1000 步计时
   - 如果预估总耗时 > 5 分钟 → 改用并行 DP 版本
   - 线程数 = min(CPU 核心数, 曲线位数/8)（从 `detect_env.py` 或 `os.cpu_count()` 获取）
   - 预期加速: ~50x（8 线程 vs 单线程）
   - C 多线程 DP 版本编译+调试 ~60 分钟

5. **验证**（~10 分钟）
   - C 输出与 Python 原型（小规模）一致
   - 用 Unicorn 模拟原二进制的验证函数确认结果

---

## 常见陷阱

| 陷阱 | 说明 |
|------|------|
| 忘记 mod n vs mod p | 曲线坐标 mod p，标量运算 mod n，混淆会导致完全错误的结果 |
| 点在曲线上检查 | 每次点运算后检查结果是否在曲线上，帮助发现计算错误 |
| 无穷远点处理 | 点加时两个相同点需要用 point_double 而非 point_add |
| 字节序 | 二进制中的大整数可能是大端序，需要转换 |
| 素性检查 | 曲线参数 n 必须是素数，否则 Pollard's rho 不适用 |
| n > p 异常 | 某些库（如 CryptoPP）接受 n > p 的曲线，违反 Hasse's bound 但仍可用。必须严格区分 mod n 和 mod p |
| 仿射 vs Jacobian 坐标 | 仿射坐标快但每次点加需要模逆（费马小定理 ~64 次模乘）；Jacobian 不需要模逆但多了 Z 坐标运算。64-bit 曲线仿射更快 |
| DP mask 选择 | d 太小 → DP 表爆炸（内存不足）；d 太大 → 碰撞太慢。推荐 d = 曲线位数/2 - 4 |
| MSVC 无 `__int128` | MSVC 用 `__umul128`（`#include <intrin.h>`）实现 64x64→128，或用 Barrett reduction 避免除法 |
