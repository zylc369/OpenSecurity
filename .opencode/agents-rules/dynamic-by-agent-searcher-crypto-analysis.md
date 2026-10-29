<domain_sources>

## 领域：密码分析

### 优先来源

1. **SageMath 文档** — `https://doc.sagemath.org/`
   `IntegerLattices`、`EllipticCurve`、`PolynomialRing`、`matrix.kernel()` 等的主要参考。使用 `websearch` 配合 "sagemath <concept>"。

2. **CTF writeup 聚合站**：
   - `https://ctftime.org/writeups` — 按 tag（`crypto`/`cryptography`）+ 赛事 + 年份过滤
   - `https://github.com/p4-team/ctf` — 社区存档（2023 后停更）
   - 特定赛事标签：`"hacklu crypto"`、`"plaidctf crypto"`、`"google ctf crypto"`

3. **CTF Wiki** — `https://ctf-wiki.org/`
   中文社区最系统的 CTF 知识库，Crypto 章节覆盖 RSA/格/ECC/背包/离散对数。

4. **CryptoHack** — `https://cryptohack.org/`
   现代密码学挑战平台，分类完整：RSA、Lattices、ECC、Isogenies、Diffie-Hellman。

5. **factordb** — `https://factordb.com/`
   已知因式分解数据库。在攻击大型 RSA 模数前先查询。

6. **Alpertron ECM** — `https://www.alpertron.com.ar/ECM.HTM`
   在线 ECM + SIQS 分解器，CTF 中等规模 n 分解首选。

7. **RsaCtfTool** — `https://github.com/RsaCtfTool/RsaCtfTool`
   自动化 RSA 攻击套件。文档说明了哪种攻击适用于哪种 RSA 特征。

8. **经典密码学论文（必读）**：
   - Coppersmith 1996 — 一元模多项式的小根
   - Howgrave-Graham 1997 — 扩展到二元
   - Wiener 1990 — 短 RSA 私钥指数
   - Boneh-Durfee 1999 — 改进的短指数攻击
   - Nguyen-Stern 1997 — 针对 knapsack / 截断签名的格攻击

   > 检索方式：在 ePrint（`https://eprint.iacr.org/`）中搜索"作者名 + 关键词"（如 `"Coppersmith small roots"`、`"Boneh Durfee"`）。ePrint 主要收录 2007 年后的预印本，更早的论文改用 Google Scholar / DBLP 按标题定位。

9. **PyCryptodome 文档** — `https://pycryptodome.readthedocs.io/`（实现参考，非情报来源）
   标准 Python 密码库 API（AES 模式、填充、哈希）。

10. **ePrint (IACR)** — `https://eprint.iacr.org/`
    密码学研究预印本 — 在标准攻击失败时搜索。

### 查询术语约定

- 包含攻击族：`"LLL lattice attack"`、`"Coppersmith small roots"`、`"HNP hidden number problem"`、`"Bleichenbacher padding oracle"`
- 包含结构：`"RSA short d"`、`"RSA small e"`、`"RSA multi-prime"`、`"Paillier homomorphic"`、`"Goldwasser-Micali"`
- 对于 ECC：包含曲线/问题（`"P-256 invalid curve attack"`、`"ECDLP Pollard rho"`、`"anomalous curve smart attack"`）
- 对于对称加密：包含模式+缺陷（`"AES-CBC padding oracle"`、`"DES weak key"`、`"RC4 bias"`）
- 对于哈希：包含属性（`"MD5 collision"`、`"length extension MD5"`、`"SHA1 chosen prefix"`）
- 对于离散对数：`"BSGS"`、`"Pohlig-Hellman"`、`"index calculus"`、`"nested CRT"`
- 对于格的其他应用：`"orthogonal lattice attack"`、`"subset sum LLL"`、`"approximate GCD"`
- 对于现代原语：`"isogeny SIDH attack"`、`"lattice-based KEM"`
- 对于 PRNG：`"LCG state recovery"`、`"Mersenne Twister untwist"`
</domain_sources>
