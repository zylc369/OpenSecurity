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
# 一次性部署（项目根目录执行; 自动生成 PSK 并打印）
./deploy-relayd.sh <VPS_IP> [SSH_USER=root] [--ssh-port <端口>] [--dry-run] [--restart]
#   --ssh-port   VPS SSH 端口（非标端口必填，如 29982）
#   --dry-run    预检只打印命令不执行
#   --restart    已部署过，仅同步代码并重启服务
# PSK 首次部署自动生成并打印 → 记录下来供三端配置; 重复部署沿用已生成的

# 运维（非标 SSH 端口记得 -p）
ssh -p <SSH_PORT> root@<VPS> systemctl status remote-relayd
ssh -p <SSH_PORT> root@<VPS> journalctl -u remote-relayd -f
```

内存占用 ~60-80MB（1G VPS 富余）。端口: TCP+UDP 41000（云安全组须放行）。

## 二、MacMini（gateway 节点）

`.ai_env` 配置（也可不配——首次运行 `start-remote-node.sh` 交互式引导补齐）:
```
RELAY_HOST=<VPS_IP>
RELAY_PSK=<PSK>
REMOTE_NODE_ID=<节点ID，如 macmini>
P2P_GATEWAY_ENABLE=1
CONTROL_RESIDENT=1          # 常驻模式（禁用空闲心跳自杀——节点机必配）
CONTROL_API_KEY=<随机token>  # 自动生成也行: 留空时 start-remote-node.sh 生成并打印
                             # 作用: ① 绑 0.0.0.0 + 局域网信任放行（含管理 UI，免令牌）
                             #      ② HTTP 直连模式的 Bearer 凭证（访问端填同值）
```

启动（一等入口，全自动）:
```bash
./start-remote-node.sh          # venv 自举→依赖→配置初始化→模型 ensure→独立会话启动
./start-remote-node.sh --check  # 仅预检不启动
./start-remote-node.sh --skip-tts --skip-models   # 跳过 TTS/模型下载（快速启动）
```
自动完成: 三必需模型（BGE-M3/Reranker/GLM-OCR）+ kokoro TTS 下载就绪（MODEL_WAIT_TIMEOUT_SEC=3600）; HF 端点双端实测择优（镜像 >2x 才固化）。SSH 断开后进程不死（独立会话），日志: `logs/remote-node.log`，停止: `kill -TERM -<打印的pid>`。

验证: 日志 `remote gateway 已启动` + relayd 日志出现注册。
TTS 自测: `cd .opencode/control/backend && python -m services.tts_service --smoke "你好"`。
浏览器: `http://<MacMini局域网IP>:<port>` 直接打开（局域网信任免令牌——完整 UI: 模型管理/配置/更新并重启）。

## 三、MacBook（控制台客户端）

`.ai_env`:
```
RELAY_HOST=<VPS_IP>
RELAY_PSK=<PSK>
REMOTE_NODE_ID=<要连的节点ID>
P2P_CLIENT_ENABLE=1        # 0=回退 HTTP 直连
REMOTE_CONSOLE_URL=http://<MacMini局域网IP>:<port>   # HTTP 直连模式用（P2P 关闭时的回退）
REMOTE_CONSOLE_TOKEN=<节点的 CONTROL_API_KEY 值>      # HTTP 直连的 Bearer 凭证（两键一值:
                                                          # 节点侧叫 CONTROL_API_KEY，访问端填这里）
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
| 手动机能连、朗读失败 | relayd 日志（journalctl -u remote-relayd）有无 lookup；client `/health`（网关 127.0.0.1:18888/health） |
| 打洞总是失败走中继 | 家宽 NAT 类型（光猫桥接+路由器拨号改善）; 中继兜底期间功能不受影响（延迟以实测为准） |
| relayd 拒绝一切连接 | PSK 不一致（三端比对）; failban 触发（等 10 分钟或重启服务） |
| 控制台切远程失败 | P2P_CLIENT_ENABLE=1 且 PSK/RELAY_HOST 完整; relayd/节点在线 |
| TTS 503 | MacMini 模型文件/pip 依赖; `--smoke` 自测 |
| 前缀变化后直连失效 | STUN 60s 自动刷新; 中继兜底期间自动恢复 |
| **VPS 重启了怎么办** | 双侧自愈，无需人工: ① relayd 经 systemd `enable` 开机自启（`Restart=always` 崩溃也拉起）② gateway 感知信令断开后指数退避自动重连（1s→2s→…→30s 封顶，重连后重新注册+STUN 刷新）③ client 下次请求时路径重建 |

## 安全基线

- 全链路 Noise NNpsk2（PSK 认证+前向保密）; VPS 只见密文
- relayd 封禁: 同 IP 5 分钟内握手失败 10 次 → 封 10 分钟
- 本地网关仅监听 127.0.0.1（Legado 本机访问）
- 节点控制台分层信任: 本机全放行 → 局域网（配置 CONTROL_API_KEY 后信任放行，含管理 UI）→ 公网来源白名单路径 + Bearer 令牌兜底（防 0.0.0.0 绑定意外暴露）
