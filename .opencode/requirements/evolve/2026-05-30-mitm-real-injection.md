# 需求文档: Flutter MITM 真实内容注入方案沉淀

> 日期: 2026-05-30
> 来源: FactsDroid MITM 分析复盘
> 状态: 待实施

---

## §1 背景与目标

### 背景

本次 FactsDroid MITM 分析中，知识库 `mitm-methodology.md` 的"方案 B"指导 AI 使用 `read() Hook + popen("curl")` 做 MITM 响应篡改。但该方案**只能日志篡改结果，不能让 APP 显示篡改内容**。

AI 花了约 25 分钟试错后，发现了一个未被知识库覆盖的"方案 D"：
1. 将自签 CA 安装到 Android 系统 CA 目录
2. TrustBuiltinRoots 加载系统 CA（包含我们的 CA）
3. 通过 Frida hook（getaddrinfo + connect）重定向流量到本地 HTTPS 代理
4. 代理用 CA 签发站点证书，APP 信任该证书
5. 代理篡改响应 → **APP 实际显示篡改内容**

### 目标

1. 补充"方案 D"到 `mitm-methodology.md`，让 AI 下次直接选对方案
2. 修复 connect hook 模板的 IPv6 盲区
3. 沉淀 Python HTTPS MITM 代理脚本
4. 补充常见失败模式（iptables crash、IPv6 不通）

### 预期收益

- 上下文: 不再需要 AI 从零摸索 MITM 注入方案
- 轮次: 改进前 ~30 轮试错 → 改进后 ~5 轮
- 速度: 省约 40 分钟
- 准确度: 消除"方案 B 能注入"的认知盲区

---

## §2 技术方案

### 改动 1: 更新 `mitm-methodology.md`

**文件**: `$AGENT_DIR/knowledge-base/mitm-methodology.md`（183 行）

改动内容:

1. **§2 决策树增加"方案 D"分支**:
   - Flutter 应用 + 需要真实 MITM 注入 → 方案 D
   - 方案 B 降级为"仅需日志/证明拦截"时使用

2. **新增 §2.5 "方案 D: 系统CA注入 + SSL Bypass + HTTPS 代理"**:
   - 完整描述: CA 安装 → TrustBuiltinRoots → getaddrinfo+connect hook → HTTPS 代理 → 篡改响应
   - CA 安装步骤（openssl hash 计算、/system/etc/security/cacerts/ 推送）
   - adb reverse 端口映射
   - 关键前提: TrustBuiltinRoots 必须在代理连接之前被调用

3. **修复 §3.4 connect hook 模板**:
   - 增加 AF_INET6 处理: 将 IPv6 loopback (::1) 转为 IPv4 127.0.0.1
   - 增加 onLeave 调试日志（可选，帮助排查）
   - 修正 `Memory.allocUtf8String` 为全局预分配（避免 GC 回收）

4. **§4 常见失败模式新增 3 条**:
   - iptables DNAT 在模拟器上导致 perfetto_hprof crash
   - getaddrinfo 返回 IPv6 (::1) 导致 adb reverse 不工作
   - connect hook 中 Memory.allocUtf8String 可能被 GC 回收

### 改动 2: 新增 `mitm_proxy.py` 脚本

**文件**: `$AGENT_DIR/scripts/mitm_proxy.py`（新增）

功能:
- 生成自签 CA（或复用已有）
- 用 CA 签发目标域名的站点证书（含 SAN）
- 监听 HTTPS，接收 TLS 连接
- 转发 HTTP 请求到真实服务器
- 篡改 JSON 响应中的指定字段
- 更新 Content-Length 头

用法:
```bash
python3 $AGENT_DIR/scripts/mitm_proxy.py \
  --listen-port 44300 \
  --target-host uselessfacts.jsph.pl \
  --target-port 443 \
  --tamper-field text \
  --tamper-value "MITM HACKED!"
```

### 改动 3: 更新 `registry.json`

**文件**: `$AGENT_DIR/scripts/registry.json`（42 行）

新增 mitm_proxy 条目。

---

## §3 实施规范

### 改动范围表

| 文件 | 操作 | 行数变化 |
|------|------|---------|
| `$AGENT_DIR/knowledge-base/mitm-methodology.md` | 修改 | +100/-5 |
| `$AGENT_DIR/scripts/mitm_proxy.py` | 新增 | +130 |
| `$AGENT_DIR/scripts/registry.json` | 修改 | +15 |

### §3.1 实施步骤拆分

**步骤 1. 更新 `mitm-methodology.md` — §2 决策树和方案 D 描述**

- 文件: `$AGENT_DIR/knowledge-base/mitm-methodology.md`
- 预估行数: 新增约 60 行
- 验证点: 文件可被 AI 正确引用；方案 D 包含完整的 CA 安装步骤、代理配置流程、前提条件
- 依赖: 无

**步骤 2. 更新 `mitm-methodology.md` — §3.4 connect hook 模板修复**

- 文件: `$AGENT_DIR/knowledge-base/mitm-methodology.md`
- 预估行数: 修改约 30 行
- 验证点: 模板包含 AF_INET6 处理代码；预分配 redirectStr；代码语法正确
- 依赖: 无

**步骤 3. 更新 `mitm-methodology.md` — §4 失败模式补充**

- 文件: `$AGENT_DIR/knowledge-base/mitm-methodology.md`
- 预估行数: 新增约 15 行
- 验证点: 表格包含 iptables crash、IPv6 不通、GC 回收三条新记录
- 依赖: 无

**步骤 4. 新增 `mitm_proxy.py` 脚本**

- 文件: `$AGENT_DIR/scripts/mitm_proxy.py`
- 预估行数: 新增约 130 行
- 验证点: `python3 -c "compile(open('<file>').read(), '<file>', 'exec')"` 语法检查通过；`python3 <file> --help` 输出正确；无 openssl 时优雅报错
- 依赖: 无

**步骤 5. 更新 `registry.json`**

- 文件: `$AGENT_DIR/scripts/registry.json`
- 预估行数: 新增约 15 行
- 验证点: `python3 -c "import json; json.load(open('<file>'))"` 验证 JSON 有效
- 依赖: 步骤 4

---

## §4 验收标准

### 功能验收

- [ ] 方案 D 描述完整，包含：CA 安装、TrustBuiltinRoots 调用、流量重定向、代理配置
- [ ] connect hook 模板支持 AF_INET6
- [ ] `mitm_proxy.py --help` 输出正确
- [ ] registry.json 中 mitm_proxy 条目格式正确

### 回归验收

- [ ] 现有方案 A/B/C 的描述未被破坏
- [ ] 现有脚本（manage_frida、dex_dump）的 registry 条目未受影响
- [ ] 知识库文件间的交叉引用路径仍使用 `$AGENT_DIR`/`$SHARED_DIR`

### 架构验收

- [ ] 新文件放在正确的目录（脚本 → `$AGENT_DIR/scripts/`，知识 → `$AGENT_DIR/knowledge-base/`）
- [ ] 知识库文件自包含（不依赖主 prompt 上下文即可理解）
- [ ] Agent prompt 未增加行数（本次只改知识库，不改 prompt）

---

## §5 与现有需求文档的关系

本次改动是独立的知识/工具沉淀，不依赖未完成的需求文档。
