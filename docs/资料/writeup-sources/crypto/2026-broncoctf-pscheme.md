---
来源: https://exploitnotes.hashnode.dev/bronoctf-custom-cipher-writeup
类型: websearch-highlights（站点 403 反爬，无法直接下载；以下为搜索引擎摘录的技术要点）
获取日期: 2026-09-12
---

# BroncoCTF PScheme（Custom Cipher Writeup）技术要点摘录

## 方案结构

- `pscheme.py` 实现玩具"加密"方案：把 flag 每 4 字节 chunk 编码为额外根，直接乘进公开多项式
- `keygen`：选 64 个私有根（范围 [1, 255]），构造 monic degree-64 多项式 `pub = ∏(x - root_i)`。`pub` 打印在 `====PUBLIC KEY====` 下（`to_distrib_form` 丢弃首项系数，monic 时恒为 1）
- `encrypt`：Python 引用语义——`public = public * root_poly` 只重绑定局部名，不改调用方的 `pub` → **每个 chunk 都用同一个完整已知的 degree-64 公钥加密**，不是累积的
- 每 chunk 密文 = `pub * (x-m0)(x-m1)(x-m2)(x-m3)`，degree-68 monic 多项式（同样省略首项 1）
- `order` 值以 2 bit 一组打包：第 i 小的消息字节在原消息中的原始索引——即如何把排序后的根还原为消息顺序的置换表

## 攻击链

```
enc.txt (public key + per-chunk ciphertext)
  → 补回隐含的首项 1，重建 monic 公钥多项式
  → 每 chunk：多项式长除法 ct_poly / pub_poly → degree-4 monic 商（根 = 4 个明文字节值）
  → 商的根暴力搜索（根 ∈ [0,255]，试除 + synthetic deflation，无需四次方程求根公式）
  → order 字段 2-bit scatter 还原原始字节顺序
  → 拼接 chunk、去 null padding → FLAG
```

## 关键漏洞

| # | 问题 | 影响 |
|---|------|------|
| 1 | 公钥对每 chunk 复用且完整披露 | 多项式除法即可隔离每 chunk 的加根，私钥根集完全无关 |
| 2 | "加密"只是把明文值作为根乘进多项式 | 已知因式分解的公开多项式根可平凡恢复（无隐藏、无随机性） |
| 3 | 根搜索空间仅 [0,255]（ASCII 字节） | 暴力 + deflation 毫秒级解每个四次式 |
| 4 | order 是无密钥的确定性 bit-pack 置换 | 拿到排序根后平凡可逆 |

## 代码要点（试除+synthetic deflation 求 0-255 整数根）

```python
def int_roots(coeffs, lo=0, hi=255):
    coeffs = coeffs[:]
    roots = []
    for _ in range(len(coeffs) - 1):
        for r in range(lo, hi + 1):
            val = 0
            for c in coeffs: val = val * r + c   # Horner 求值
            if val == 0:
                roots.append(r)
                new_coeffs = [coeffs[0]]
                for c in coeffs[1:-1]:
                    new_coeffs.append(new_coeffs[-1] * r + c)
                coeffs = new_coeffs[:-1] if len(new_coeffs) > 1 else new_coeffs
                break
        else:
            break
    return roots
```
