# remote-p2p 三端部署与联调

> wire protocol 权威规范: `services/remote_relayd/protocol.md`（含测试向量附录）
> 需求文档: `.opencode/requirements/evolve/2026-10-10-remote-p2p-transport.md`

## 架构回顾

```
手机(Legado+remote-link SDK) ──┐
                              ├─ 直连 UDP（打洞成功，常态零中继流量）
MacBook 控制台 backend ────────┤      ▲ 信令/打洞协调/中继兜底
                              ▼      │
                          relayd（VPS: 搬瓦工 2C/1G）
                              ▲      │
MacMini backend(同款代码) ─────┘──────┘（gateway 节点角色）
```

## 一、VPS（relayd）

```bash
# 一次性部署（backend 目录执行; 自动生成 PSK 并打印）
bash tools/relay-deploy/setup.sh <VPS_IP>
# 输出的 PSK 记录下来 → 三端配置用

# 运维
ssh root@<VPS> systemctl status remote-relayd
ssh root@<VPS> tail -f /var/log/remote-relayd/relayd.log
```

内存占用 ~60-80MB（1G VPS 富余）。端口: TCP+UDP 41000（云安全组须放行）。

## 二、MacMini（gateway 节点）

`.ai_env` 配置:
```
RELAY_HOST=<VPS_IP>
RELAY_PSK=<PSK>
REMOTE_NODE_ID=macmini
P2P_GATEWAY_ENABLE=1
# TTS 模型（可选——朗读需要）:
#   pip install kokoro-onnx soundfile
#   模型放 ~/.cache/opensecurity/tts/{kokoro-v1_0.onnx,voices.bin}
```

验证: 启动 backend → 日志 `remote gateway 已启动` + relayd 日志出现注册。
TTS 自测: `python -m services.tts_service --smoke "你好"`。

## 三、MacBook（控制台客户端）

`.ai_env`:
```
RELAY_HOST=<VPS_IP>
RELAY_PSK=<PSK>
REMOTE_NODE_ID=macmini
P2P_CLIENT_ENABLE=1        # 0=回退 HTTP 直连（现状）
REMOTE_CONSOLE_URL=http://<MacMini局域网IP>:<port>   # 仍需配置（P2P 关闭时用）
```

验证: 远程 TAB 切换远程 → embed/rerank/ocr 经 P2P（relayd 日志可见直连/中继路径）。

## 四、手机（Legado）

1. 构建安装（legado-with-MD3 仓）: `./gradlew :app:assembleAppDebug`
2. 打开 RemoteLink 设置：设置 → 「RemoteLink 朗读」入口（或 adb: `am start -n io.legado.app/com.opensecurity.remotelink.ui.ConfigActivity`）
3. 录入 VPS IP / PSK / 节点 ID / 本地端口 → 启用
4. Legado 朗读引擎新建 HTTP-TTS:
   - URL: `http://127.0.0.1:18888/tts?text={{speakText}}&speed={{speakSpeed}}`
   - contentType: `audio/wav`; **concurrentTasks 必须为 1**

## 故障排查矩阵

| 症状 | 排查 |
|------|------|
| 手动机能连、朗读失败 | relayd 日志有无 lookup；client `/health`（网关 127.0.0.1:18888/health） |
| 打洞总是失败走中继 | 家宽 NAT 类型（光猫桥接+路由器拨号改善）; 中继仍可用（50-80ms） |
| relayd 拒绝一切连接 | PSK 不一致（三端比对）; failban 触发（等 10 分钟或重启服务） |
| 控制台切远程失败 | P2P_CLIENT_ENABLE=1 且 PSK/RELAY_HOST 完整; relayd/节点在线 |
| TTS 503 | MacMini 模型文件/pip 依赖; `--smoke` 自测 |
| 前缀变化后直连失效 | STUN 60s 自动刷新; 中继兜底期间自动恢复 |
| **VPS 重启了怎么办** | 双侧自愈，无需人工: ① relayd 经 systemd `enable` 开机自启（`Restart=always` 崩溃也拉起）② gateway 感知信令断开后指数退避自动重连（1s→2s→…→30s 封顶，重连后重新注册+STUN 刷新）③ client 下次请求时路径重建 |

## 安全基线

- 全链路 Noise NNpsk2（PSK 认证+前向保密）; VPS 只见密文
- relayd 封禁: 同 IP 5 分钟内握手失败 10 次 → 封 10 分钟
- 本地网关仅监听 127.0.0.1（Legado 本机访问）
