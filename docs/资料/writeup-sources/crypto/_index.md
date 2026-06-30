# Crypto 方向源文档索引

> 创建: 2026-06-30, 更新: 2026-06-30

## ZKP / FHE / PQC 参考资料

| 文件 | 来源 | 覆盖技术 |
|------|------|---------|
| zkdocs-fiat-shamir.md | zkdocs.com (Trail of Bits) | Fiat-Shamir 伪造：哈希输入缺失导致证明不绑定 statement，含完整攻击步骤 |
| zkdocs-hvzk.md | zkdocs.com (Trail of Bits) | HVZKP 被恶意验证者利用：Two-Prime-Divisor（gcd 提取因子）、Short Factoring Proof |
| castryck-decru-sidh-readme.md | github.com/GiacomoPope/Castryck-Decru-SageMath | SIDH 密钥恢复攻击（Glue-and-Split）：完整 SageMath 实现，SIKEp434≈10min |

## pcw109550 实战 Writeup 解题脚本

| 文件 | 赛事/年份 | 覆盖技术 |
|------|----------|---------|
| pcw109550-2023-Dice-BBBB-solve.sage | DiceCTF 2023 | LCG 参数选择 + Coppersmith 攻击 |
| pcw109550-2023-TSG-Delta-Force-solve.sage | TSG CTF 2023 | 奇异曲线 DLP（复合环上 → 约化为加法群 / Pohlig-Hellman）|
| pcw109550-2023-TSG-Delta-Force-*.py/sage/README.md | TSG CTF 2023 | 同上（含完整题目 + 椭圆曲线辅助 + writeup）|
| pcw109550-2022-RCTF-S2DH-solve.sage | RCTF 2022 | SIDH/SIKE 破解（Castryck-Decru 攻击实战）|
| pcw109550-2022-CODEGATE-Final-README.md | CODEGATE 2022 Final | Plonkup + Frozen Heart（ZKP 漏洞）+ Solidity Optimizer Bug（52KB 详细 writeup）|
| pcw109550-2022-CODEGATE-Final-solve.py | CODEGATE 2022 Final | 同上的解题脚本 |
| pcw109550-2022-angstromCTF-logloglog-solve.sage | angstromCTF 2022 | Pohlig-Hellman（素数幂阶群的离散对数）|

## 调研报告
- `docs/资料/crypto-zkp-fhe-pqc-research/调研报告.md` — ZKP/FHE/PQC 完整调研（趋势+技术清单+工具链+方法论+缺失识别）
