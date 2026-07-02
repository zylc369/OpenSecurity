# 智能合约（EVM/Solidity）CTF 攻击方法论

> 遇到 Solidity/EVM/Foundry/Hardhat/智能合约题时读取。覆盖环境识别、攻击模式速查、核心漏洞的识别-检查-利用。不依赖主 prompt 上下文。

---

## 1. 环境与方案识别

**识别信号**：
- `.sol` 文件；Foundry（`foundry.toml`/`forge-std/`/`script/Deploy.s.sol`）；Hardhat（`hardhat.config.js`）
- RPC 端点（HTTP/WS）、私钥或助记词、链 ID
- 题目目标：通常有 `isSolved()` 函数，返回 true 的条件（如余额达标、成为 owner、selfdestruct 合约）

**读题优先**：找 `isSolved()` 的判定条件 → 反推要达成的链上状态 → 定位能改这个状态的合约函数。

**环境与交互工具**：
- Foundry：写攻击合约作为测试，`forge test -vvv`；主网题用 `forge test --fork-url <RPC>` 分叉复现
- `cast send <to> <sig> <args> --rpc-url <RPC> --private-key <KEY>`：发交易
- `cast call <to> <sig>`：读 view 函数（不发交易）

---

## 2. 攻击模式速查表

| 模式 | 识别线索（看到即往这条路想） |
|------|-----------|
| delegatecall 存储覆盖 | `delegatecall` + 目标可控 + storage 布局可操纵 owner/token |
| delegatecall 上下文 | 库合约 delegatecall 中用 msg.sender 做权限 |
| 重入 | 外部调用（`.call{value:}`/`transfer`/token transfer）在状态更新前 |
| access control | 敏感函数（mint/withdraw/setOwner）无 `onlyOwner` 或 public |
| tx.origin 钓鱼 | 用 `tx.origin` 而非 `msg.sender` 判权限 |
| 整数溢出 | `unchecked{}` / assembly + 减法/乘法（Solidity ≥0.8 默认检查，需绕过点） |
| 签名重放 | 验签无 nonce 或同一签名可多次用 |
| ECDSA 可延展 | 验签未规范化 s（s vs n-s）/未限定 v |
| ecrecover address(0) | 未检查 `ecrecover(...)` 返回值（无效签名返回 address(0)） |
| 链上随机数 | `block.timestamp`/`blockhash`/`block.prevrandao` 做随机源 |
| flash loan 操纵 | 价格/治理快照基于可借资产 |
| Oracle 操纵 | 价格来自单一 DEX pool / 可被 flash loan 操纵 |
| selfdestruct 强制转账 | 强制 ETH 进非 payable 合约（绕过余额检查） |
| ERC20/ERC777 钩子重入 | transfer 触发接收方回调（tokensReceived） |
| 未检查 call 返回值 | `.call`/`.send` 后未查 `success` |
| view 不确定 | `view` 函数依赖可变状态（block/余额） |
| abi.encodePacked 碰撞 | 变长参数拼接哈希（"abc"+"def" == "ab"+"cdef"） |
| Merkle proof | proof 未校验叶子唯一/可伪造中间节点 |
| gas 操纵 | callee 故意耗光 gas 使调用失败 |

---

## 3. delegatecall 滥用

**场景**：合约用 `delegatecall` 调外部合约/库，但 storage 布局可操纵，或上下文（msg.sender/this/balance）与预期不符。

**存储覆盖原理**：delegatecall 在**调用方的 storage 上下文**执行目标代码。目标合约写它自己的 slot N，实际写的是调用方的 slot N。
- 攻击：控制 delegatecall 目标 → 目标合约写入 → 覆盖调用方的 owner/token 等关键变量
- 检查：找 `delegatecall` 的目标是否可控 + 比对调用方与目标的 storage 布局（变量声明顺序决定 slot）

**上下文不匹配**：delegatecall 保持 `msg.sender`/`msg.value`/`this`=调用方。库合约若用 msg.sender 做权限，实际是原始调用者，可被绕过。

**案例（R3CTF 2024 DAO）**：`R3Dao.execute` 对 `proposal.recipient` 做 delegatecall：
```solidity
(bool success, ) = proposal.recipient.delegatecall(payload);
```
`proposal.recipient` 经治理提案可控。delegatecall 到攻击合约 → 攻击合约代码在 R3Dao 上下文执行 → 可操纵 R3Dao storage / 配合 Uniswap pair 偷 ETH。
- 攻击路径：flash loan 借 R3Token 获投票权 → propose 指定 recipient=攻击合约 → vote 凑够 `>totalSupply/2` → execute delegatecall → 攻击合约 pwn() 偷 ETH → 还款

**利用骨架（Foundry 测试）**：
```solidity
contract Exploit {
    // 被 delegatecall 调用；执行时 this/storage = R3Dao 的上下文
    function pwn(address pair, address me) external {
        // 此处可读写 R3Dao 的 storage、以 R3Dao 身份调用 Uniswap pair
    }
}
```

**检查**：delegatecall 目标可控？调用方 storage 布局？是否需配合治理/flash loan 攒权限？

---

## 4. 重入攻击

**场景**：合约在外部调用（`.call{value:}`/`transfer`/token transfer）**更新状态前**，被调方回调攻击合约重新进入。

**经典漏洞**：
```solidity
function withdraw() external {
    uint bal = balances[msg.sender];
    (bool ok,) = msg.sender.call{value: bal}("");  // 1. 先转账 → 触发攻击合约回调
    balances[msg.sender] = 0;                       // 2. 后扣余额（违反 CEI）
}
```
攻击合约 `receive()` 再次调 `withdraw()`，余额未清零 → 重复提款。

**利用**：攻击合约 `receive()`/`fallback()` 重入目标提款函数。
- 检查：外部调用是否在状态更新前（违反 Checks-Effects-Interactions 顺序）

**变体**：
- 跨函数重入：两个函数共享同一状态变量
- ERC777/ERC20 钩子重入：transfer 触发接收方 `tokensReceived` 回调（即使 ETH 转账没发生）

**防御对照**（识别题目是否"假装"防了）：ReentrancyGuard 非重入锁、CEI 顺序、`transfer`（仅 2300 gas，难重入）vs `.call`（转发全部 gas）。

---

## 5. access control 与权限漏洞

**场景**：敏感函数（mint/transfer/withdraw/setOwner/upgrade）缺权限检查。

**模式**：
- 函数 `public`/`external` 但无 `onlyOwner` 等修饰符
- 用 `tx.origin` 判权限（钓鱼：攻击合约诱导用户调用，`tx.origin`=用户通过，但 `msg.sender`=攻击合约）
- constructor 名拼写错误（旧 Solidity，变成普通函数可反复"初始化"）
- 可见性默认（Solidity <0.5 函数默认 public，漏标 internal/public 有区别）

**tx.origin 钓鱼利用**：
```solidity
// 目标漏洞
require(tx.origin == owner, "not owner");
// 攻击：诱导 owner 调用攻击合约，攻击合约再调目标 → tx.origin=owner 通过
```

**检查**：每个敏感函数的权限修饰符；owner 设置逻辑（constructor/初始化函数）；visible 性声明。

---

## 6. 整数溢出

**场景**：算术溢出/下溢导致余额/计数绕过。

**Solidity 版本边界（关键）**：
- **≥0.8**：算术**自动**溢出检查（溢出 revert）。要溢出必须显式 `unchecked{}` 或 inline assembly
- **<0.8**：不检查，直接 wrap around（经典溢出）

**利用**：
```solidity
unchecked { balance -= amount; }   // amount > balance 时下溢成 type(uint256).max
// assembly 块内算术也不检查溢出
assembly { s := sub(s, 1) }        // s=0 时下溢
```
- 下溢成大数 → 绕过余额检查 / 循环计数 / mint 巨量 token

**检查**：pragma solidity 版本；`unchecked` 块；inline assembly 内算术。

---

## 7. 签名验证漏洞

**场景**：合约用 ECDSA 验签授权，验签有缺陷。

**签名重放**：同一签名可多次使用（缺 nonce 或未标记已用 hash）。
- 检查：验签后是否记录 `used[hash] = true`

**ECDSA 可延展性**：签名 `(r, s, v)` 中，`s` 与 `n-s` 都对同一消息有效。若合约未要求低 s（`s ≤ n/2`，EIP-2 规范化），攻击者用 `(r, n-s, v')` 构造新签名重放。
- 检查：是否要求 s 在下半区间（OpenZeppelin ECDSA 库默认 enforce）

**ecrecover 返回 address(0)**：`ecrecover` 对无效签名返回 `address(0)`。若合约未校验返回值，且 owner 恰为 address(0) 或逻辑跳过，攻击者伪造无效签名通过。
```solidity
address signer = ecrecover(hash, v, r, s);   // 无效签名返回 address(0)
require(signer == owner);                     // 若 owner 未设=address(0)，绕过
```
- 检查：`ecrecover` 返回值是否校验非零。

---

## 8. 链上随机数弱点

**场景**：合约用链上数据做随机源，攻击者可预测。

**弱点源**：
- `block.timestamp`（矿工/验证者可操纵 ±几秒）
- `blockhash`（仅最近 256 块可得，更早返回 0）
- `block.prevrandao`（PoS，可被验证者影响）
- `keccak256(区块数据)`：攻击合约可在**同交易**内算出同样结果

**利用**：攻击合约先算出目标将用的"随机数"再提交：
```solidity
// 漏洞
uint lucky = uint(keccak256(abi.encodePacked(block.timestamp, msg.sender)));
// 攻击合约：同区块同 sender 算同样 keccak，预知 lucky，再调目标
uint guess = uint(keccak256(abi.encodePacked(block.timestamp, address(this))));
require(guess == lucky_target);
```

**检查**：随机源是否链上可预测；是否用**未来** blockhash（commit-reveal 模式才安全）。

---

## 9. flash loan 与 Oracle 操纵（基础）

**flash loan**：无抵押借巨量资产，**同交易内**还清。用于操纵依赖资产价格/数量/投票权的逻辑。
- 利用流程：借资产 → 操纵价格/治理快照 → 获利/达标 → 还款（一笔交易）
- 检查：价格/投票权/快照是否基于可借（流动性大的）资产

**Oracle 操纵**：价格来自单一 DEX pool（如 Uniswap pair）→ flash loan 倾倒资产扭曲瞬时价格 → 资金盘按扭曲价格结算。
- 检查：价格源是否单一/瞬时；是否用 **TWAP**（时间加权平均价，抗瞬时操纵）

**利用（Foundry 分叉主网）**：
```bash
forge test --fork-url <主网RPC> -vvv   # 分叉主网，可 flash loan 真实 Unisgov/Aave
```

> DeFi 深度（治理快照攻击/AMM 算法 bug/sandwich）见速查表 §2，遇题结合具体协议深入。

---

## 10. 工具速查（Foundry/Slither/cast）

**Foundry**：
```bash
forge test -vvv                     # 跑测试看 trace
forge test --fork-url $RPC -vvv     # 分叉主网复现（DeFi 题必备）
forge inspect <Contract> storage-layout   # 查 storage 布局（delegatecall 攻击必备）
```
测试内 cheatcodes：`vm.startPrank(attacker)` 模拟攻击者发交易；`vm.deal(addr, 100 ether)` 给 ETH；`vm.roll(blockNum)` 控块高。

**Slither（静态审计）**：
```bash
slither <合约目录>                   # 自动找重入/未检查 call/权限等模式
```

**cast（命令行交互）**：
```bash
cast send $TO "func(uint256)" 42 --rpc-url $RPC --private-key $KEY
cast call $TO "owner()" --rpc-url $RPC        # 读 view 函数
cast 4byte 0x9e5faafc                          # 解函数选择器 → 签名
```

---
