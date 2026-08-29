# 分析-hello







这是我对题目的拷贝：
```

描述
hello! can you help me to recover the message?

Flag format is: flag[:-1] + _ + sha256(flag[11:-1])[:16] + "}"


Connection Info：nc 34.2.147.230 3000
```

题目附件（Attachments）的基于当前项目的本地路径：docs/分析/密码学/Attachments/apbq-rsa-iv/chall.sage

## 解题结果（2026-08-29，已解出）

- 原始 flag：`COMPFEST18{c0ngr4tzzz_h3ngk3rrrr_g3n3r4l1Zed_w13n3R_4ttacK}`
- 提交 flag：`COMPFEST18{c0ngr4tzzz_h3ngk3rrrr_g3n3r4l1Zed_w13n3R_4ttacK_f91f71b7c1b857d2}`

攻击：广义 Wiener。e·d≡-1 (mod φ)，φ=(p^10-1)(q^10-1)≈N^10，d<N^2.5/(√3μ) → 连分数 e/N^10 收敛子恢复 (k,d) → φ=(ed+1)/k → p^10、q^10 为 z²-sz+N^10=0 之根（s=N^10+1-φ）→ 分解 N。

解密坑：φ 不是环 Z_N[x]/(x^10-2) 单位群真指数（x^10-2 mod p 因子次数可不整除 10），需按因子分解求 λ=lcm(p^d_i-1)，用 e^{-1} mod λ 在 Z_p/Z_q 分别解密再 CRT。

求解脚本：~/bw-security-analysis/workspace/20260829_120619_b88b_crypto-analysis/{fetch.py,solver.py}（含自测与网格/BD 备用路径）