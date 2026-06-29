# 密码学分析方法论

> 总入口：识别题目类型 → 路由到对应攻击库 → 用 SageMath 求解。开始分析时先读本文件。

## 1. 类型识别（最先做）

拿到题目先判断属于哪类，再读对应攻击库。按特征匹配：

| 看到的特征 | 类型 | 去读 |
|------------|------|------|
| `n=p*q`、`e`、`c=pow(m,e,n)`；或给了 p/q 的 hint | RSA | `rsa-attacks.md` |
| 多个 `a*p+b*q`、截断比特、近似值、HNP | 格（lattice） | `lattice-attacks.md` |
| 椭圆曲线方程 `y²=x³+ax+b (mod p)`、点加法/标量乘、离散对数 `Q=kG` | ECC | `ecc-attacks.md` |
| 凯撒/维吉尼亚/单表替换/无密钥、字母频率 | 古典 | `classical-crypto.md` |
| AES/DES、CBC/ECB/CTR/GCM、padding 报错、IV 可控 | 对称 | `symmetric-and-hash.md` |
| MD5/SHA、`mac=hash(key∥msg)`、长度扩展 | 哈希 | `symmetric-and-hash.md` |
| PRNG、随机数、状态恢复 | 伪随机 | 按子类（LCG/LFSR/Mersenne Twister）查通用资料；LCG 恢复见 `symmetric-and-hash.md` §6 |
| 构造满足整除/模运算/位运算约束的输入（非给密文求明文） | 数论构造题 | `number-theory-construction.md` |

**判断不清时**：把题目所有参数列出来，看"哪个参数异常"（e 太小/太大、hint 数量、比特长度关系）——异常点就是攻击方向。

## 2. 通用求解流程

```
1. 提取全部已知量（n, e, c, hint, 曲线参数……）写进脚本常量
2. 识别攻击模式（见各攻击库的"什么时候用"）
3. 用 SageMath 构造求解（格 → matrix.LLL()；多项式小根 → small_roots()；离散对数 → discrete_log）
4. 求出 p/q/明文 → i2b → 验证 flag 格式
5. 失败 → 回溯：换攻击 / 检查参数识别 / 调格构造参数
```

## 3. SageMath 使用基础

### 3.1 何时用 sage（优先于手写）

- **格规约 LLL/BKZ**：`matrix.LLL()`、`matrix.BKZ()`——手写极易出错，必用 sage。
- **多项式小根（Coppersmith）**：`f.small_roots(X=, beta=, epsilon=)`。
- **离散对数**：`discrete_log(Q, G)`、Pohlig-Hellman 自动用。
- **椭圆曲线运算**：`EllipticCurve(...)`、点运算 `+`、`*`。
- **数论**：`factor(n)`、`nth_root`、`GF(p)`、`Zmod(n)`。

### 3.2 调用方式

```bash
# .sage 文件（含 sage 语法）
sage solve.sage

# 或 sage 跑 python
sage -python solve.py
```

### 3.3 sage 缺失时

detect_env 会检测。若缺失：
- 格攻击/Coppersmith/ECC 离散对数 → **必须先装 sage**（detect_env 会给命令：`conda install -p ~/bw-security-analysis/.venv sage`）。
- 简单 RSA（已知 p/q 直接解）、古典、对称 → 用 `gmpy2` + `sympy` 手写可行。

## 4. 大整数与编码

```python
# bytes↔int 用 Python 标准库
def i2b(n):  # int -> bytes (大端)
    return n.to_bytes((n.bit_length()+7)//8 or 1, 'big')
def b2i(b):  # bytes -> int (大端)
    return int.from_bytes(b, 'big')
# 明文整数 → bytes（flag）
flag = i2b(m)
# 检查
assert flag.startswith(b'flag') or flag.startswith(b'SEKAI')
```

`gmpy2` 基本运算：
```python
import gmpy2
d = gmpy2.invert(e, (p-1)*(q-1))   # RSA 私钥
m = pow(c, d, n)
phi = (p-1)*(q-1)
```

## 5. 模式匹配清单（速查，详见各库）

| 现象 | 攻击 | 库 |
|------|------|----|
| 同 n 不同 e | 共模攻击 | rsa |
| e 很小（如 3）+ m 小 | 直接开方 / Coppersmith | rsa |
| d 小（e 大） | Wiener / Boneh-Durfee | rsa |
| 多组 hint 线性含 p,q | LLL | lattice |
| 截断的 LCG/比特 | HNP（格） | lattice |
| 曲线阶 = p | Smart（anomalous） | ecc |
| 阶光滑 | Pohlig-Hellman | ecc |
| CBC + padding oracle | Padding Oracle | symmetric |
| `mac=hash(key∥msg)` | 长度扩展 | symmetric |

## 6. 注意

- **先验证再下结论**：求出候选明文必须 `i2b` 看是否像 flag，不能只算出数就说"解了"。
- **参数即线索**：e=3、n=2*p、hint=3 个、bits 不对称……每个异常都指向特定攻击。
- **不盲目爆破**：先模式匹配；爆破只在搜索空间极小（如古典密码位移）时。
