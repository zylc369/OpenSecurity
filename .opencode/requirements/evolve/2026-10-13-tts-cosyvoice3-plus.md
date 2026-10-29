# TTS 引擎升级: CosyVoice3-8bit（mlx-audio-plus）+ 音色库 + 模型 tags 通用化

> 需求编号: EV-2026-10-13-TTS-COSYVOICE3
> 来源: 用户听书场景实测选型（本会话三轮耳朵验收）+ 架构通用化提议（用户）
> 状态: 执行中

## §1 背景与目标

**来源**: 本地 TTS 听书选型实测（M4 Pro 三引擎对比:Qwen3-TTS/IndexTTS-2.5/CosyVoice3 + 方言/克隆/变速实验）。用户耳朵验收定案:
- 女声普通话（官方参考 + zero-shot）= 质量天花板（"挺好听，柔和、奶声奶气、欢快"）
- CosyVoice3 8bit 量化版（mlx-community 官方发布）音质过线，内存 2.84GB、RTF 0.30（M4 Pro 实测）
- 引擎 = mlx-audio-plus 0.1.8（mlx-audio 8020 stars 生态的 fork，主线作者深度参与）
- 语速 = ffmpeg atempo 0.90 后处理（用户验收"不错";librosa phase vocoder 被否"滋啦感"）
- Kokoro（现役引擎）质量不达标，全量退役

**用户核心决策**（已确认）:
1. plus 引擎 + CosyVoice3 模型 + 8bit 精度
2. 音色 = 官方女声参考（plus_cv3_s092_run2 同源）;atempo 0.90 为该音色默认可选速度;用户 Android 端另行实测播放器调速
3. 控制台后端管理引擎依赖/模型/调用（复用现有体系）
4. Kokoro 相关代码、模型全删
5. 模型安装引入 tags 通用设计（对齐 detect_py_deps.py 的 DepTag 模式）: TTS 模型非必须，`--model-tags` 圈选安装范围
6. 音色以文件形式提交仓库（wav+逐字稿，百 KB 级）;控制台提供音色管理（列表/试听/上传，无删除接口）;`/api/tts` 支持调用方选音色

**预期收益**:
- 听书质量从 Kokoro（下品）跃升到 CosyVoice3（用户上品验收）
- 模型安装体系通用化（tags 圈选）——后续任何非必须模型（TTS/其他）零特判接入
- 音色库机制——后续加音色 = 传一个 wav+文字稿（用户自助或 agent 代做）

## §2 技术方案

### 2.1 架构总览

```
调用方（Legado / 控制台前端）
   │ POST /api/tts {text, voice?, speed?}
   ▼
routes/tts.py ── GET /api/tts/voices ──→ VoiceLibrary（services/voice_library.py）
   │                                      └─ assets/voices/（wav+text+voices.json，入 git）
   ▼
TtsService（services/tts_service.py 改造）
   ├─ 本地路径: TtsWorkerClient → 常驻子进程（.venv-tts python）→ mlx-audio-plus 推理
   │    ├─ CosyVoice3-8bit（模型目录: $OPENSECURITY_HOME/models/cosyvoice3-8bit/，非 HF cache）
   │    ├─ 每请求后 mx.clear_cache()（内存纪律）
   │    ├─ 尾部静音检测 → 自动重试 1 次（输出校验）
   │    └─ speed<1 → ffmpeg atempo 后处理（变速不变调）
   ├─ 远程路径: should_use_remote → remote_client.tts_synth（P2P → MacMini 同构 worker）
   └─ LRU 缓存（键: voice+speed+text）

模型/依赖管理
   ├─ ModelAssetRegistry: CosyVoice3Asset 替换 Kokoro 条目
   │    ├─ ModelTag 枚举（SECURITY/TTS）+ ModelAsset.tags 字段（基类默认 SECURITY）
   │    └─ cache_state 目录检测 / download_worker 下载到自定义目录
   ├─ remote_node.ensure_models: --model-tags 圈选（默认 security）;skip_tts 特判删除
   └─ scripts/install_tts_deps.sh: 独立 venv（.venv-tts）+ requirements-tts.txt
        （plus 依赖不进主 venv——torch 2.14 与主栈隔离;webrtcvad 构建坑绕过注释）
```

### 2.2 关键设计决策

| 决策 | 理由 |
|------|------|
| TTS 推理走**独立 venv 常驻子进程**（worker） | plus 依赖 torch 2.14/mlx-lm 与主 venv 隔离;39GB 内存教训 → worker 内存隔离+预算回收;崩溃不拖垮控制台 |
| worker 生命周期 | TtsService 懒加载 spawn（首次合成时）;单请求超时 300s 杀进程重启;进程意外退出 → 下次请求自动重拉;空闲不主动杀（听书常驻场景） |
| 模型放**自定义目录**（非 HF cache） | 复用 Kokoro 的目录口径模式;局域网 rsync 部署简单（HF cache 结构复杂）;hf-mirror 对冷门仓库 308 回源不可靠 |
| 音色 = **仓库资产**（assets/voices/） | 百 KB 级随 git 走;MacMini update-restart 自动同步;版本可回溯 |
| voice/speed 语义 | voice=音色库 id（默认官方女声）;speed=目标速率（1.0 原速;0.9=atempo 0.9 后处理——由 worker 内执行，双机同构单点实现） |
| ffmpeg 依赖检测 | worker 启动 shutil.which("ffmpeg");speed≠1 且缺失 → 明确报错（不静默降级） |
| 音色双源 | 内置音色 = git 资产 assets/voices/（voices.json）;用户上传 = 运行时目录 $OPENSECURITY_HOME/voices/（user_voices.json）——上传不污染 git 目录，列表合并展示 |
| instruct（方言）定位 | worker 协议支持可选 instruct 字段（面向未来）;/api/tts 不暴露（方言彩蛋定位，YAGNI） |
| 静音校验 | 尾部 10s RMS<阈值 → 重试 1 次（Eric 式半截静音事故预防） |
| DepTag 不加 TTS | TTS 依赖装独立 venv（非主 venv），detect_py_deps 的 install --tags 语义是主 venv——不混用;start-remote-node --model-tags tts 触发 install_tts_deps.sh |

### 2.3 数据结构

```python
# voice_library.py
@dataclass(frozen=True)
class VoiceAsset:
    id: str            # "official_female"
    name: str          # "官方女声"
    gender: str        # "female" | "male"
    description: str
    wav: str           # assets/voices/official_female.wav
    ref_text: str      # 逐字稿（zero-shot 必需）
    default_speed: float = 1.0

# voices.json: list[VoiceAsset 字典]（清单与 wav 同目录）

# worker 协议（stdin/stdout 行式 JSON）
请求: {"id": "req-1", "op": "synth", "text": "...", "wav": "...ref路径", "ref_text": "...", "out": "/tmp/xxx.wav"}
响应: {"id": "req-1", "ok": true, "path": "/tmp/xxx.wav", "duration": 62.4, "rtf": 0.31}
     {"id": "req-1", "ok": false, "error": "..."}
```

### 2.4 接口变更

| 端点 | 变更 |
|------|------|
| POST /api/tts | body 增 voice（音色 id，默认音色库第一条）、speed 保持（服务端 atempo） |
| GET /api/tts/voices | 新增——音色列表（前端/调用方枚举） |
| POST /api/tts/voices | 新增——上传音色（multipart: wav + name/gender/description/ref_text;服务端重采样 24kHz + 时长校验 3-30s + 入库） |
| ~~DELETE~~ | **不提供删除接口**（用户要求;防引用悬空） |
| remote_client.tts_synth | 参数透传 voice/speed |

## §3 实现规范

### 改动范围表

| 文件 | 改动 | 预估行数 |
|------|------|---------|
| backend/services/model_assets.py | ModelTag 枚举 + tags 字段 + CosyVoice3Asset + 删 Kokoro 条目 | ~110 |
| backend/services/remote_node.py | --model-tags 圈选 + skip_tts 删 | ~30 |
| start-remote-node.sh | --model-tags 透传 | ~5 |
| backend/scripts/requirements-tts.txt | 新增（plus 依赖固化） | ~15 |
| backend/scripts/install_tts_deps.sh | 新增（uv venv .venv-tts + 安装） | ~40 |
| backend/scripts/tts_worker.py | 新增（常驻推理 worker: 协议+推理+clear_cache+静音校验） | ~150 |
| backend/services/voice_library.py | 新增（VoiceAsset+清单+上传入库） | ~130 |
| backend/assets/voices/* | 新增（official_female.wav 326KB + voices.json） | 资产 |
| backend/services/tts_service.py | 引擎改 worker 调用 + voice 语义 + atempo + 删 kokoro | ~120 净改 |
| backend/services/remote_client.py | tts_synth 参数扩展 | ~10 |
| backend/services/detect_py_deps.py | 删 kokoro-onnx 条目 | -3 |
| backend/routes/tts.py | voices 端点 + upload 端点 | ~60 |
| backend/tests/test_voice_library.py | 新增 | ~80 |
| backend/tests/test_tts_service.py | 改造（引擎 mock 为 worker 协议测试） | ~100 |
| backend/tests/test_model_tags.py | 新增（圈选逻辑） | ~60 |
| frontend/src/sections/ModelSection（或等价） | 模型页 tag 分组 + 音色区块 | ~120 |

### §3.1 实施步骤

```
1. tags 体系落地（model_assets.py + remote_node.py + start-remote-node.sh）
   - 文件: model_assets.py / remote_node.py / start-remote-node.sh
   - 预估行数: ~145
   - 验证点: pytest test_model_assets（现有）全绿;python -c 导入无错;
     手动构造 Registry 验证 tags 过滤函数（security 组不含 tts 条目）
   - 依赖: 无

2. CosyVoice3Asset + Kokoro 条目删除（model_assets.py）
   - 文件: model_assets.py
   - 预估行数: ~110
   - 验证点: GET /api/models（TestClient）含 cosyvoice3 条目、无 kokoro;
     cache_state 对不存在目录返回 not_cached
   - 依赖: 1

3. 音色库模块 + 官方女声入库（voice_library.py + assets/voices/）
   - 文件: voice_library.py / assets/voices/*
   - 预估行数: ~130 + 资产
   - 验证点: pytest test_voice_library（列表/查询/上传入库含 24kHz 重采样 mock）
   - 依赖: 无

4a. TTS worker 脚本（scripts/tts_worker.py）
   - 文件: scripts/tts_worker.py
   - 预估行数: ~150
   - 验证点: 协议冒烟（echo JSON | worker → 无模型时明确错误响应）;--help 可跑
   - 依赖: 无

4b. TTS 依赖清单 + 安装脚本（requirements-tts.txt + install_tts_deps.sh）
   - 文件: scripts/requirements-tts.txt / scripts/install_tts_deps.sh
   - 预估行数: ~55
   - 验证点: 本机全新 .venv-tts 安装成功（uv + 阿里镜像）;import mlx_audio 成功
   - 依赖: 无

5. TtsService 引擎改造（tts_service.py）
   - 文件: tts_service.py
   - 预估行数: ~150 净改
   - 验证点: pytest test_tts_service（worker 协议 mock: 合成/缓存命中/静音重试/atempo 调用）;kokoro 引用清零（grep）
   - 依赖: 3, 4a, 4b

6. 路由 + 远程参数（routes/tts.py + remote_client.py）
   - 文件: routes/tts.py / remote_client.py
   - 预估行数: ~70
   - 验证点: TestClient GET /api/tts/voices 200;POST /api/tts 透传 voice;
     tts_synth 签名扩展后 pyright 0
   - 依赖: 3, 5

7. Kokoro 全清理（detect_py_deps.py + 文档 + 本机缓存）
   - 文件: detect_py_deps.py / relay-deploy README / 本机模型缓存删除
   - 预估行数: ~10
   - 验证点: grep -ri kokoro backend/ start-remote-node.sh 零业务残留（pyc 除外）;
     本机 ~/.cache/opensecurity/tts 删除
   - 依赖: 2, 5

8. 前端: 模型页 tag 分组 + 音色区块
   - 文件: frontend/src（模型管理 section + 音色组件）
   - 预估行数: ~120
   - 验证点: npm run build 通过;模型页显示"安全分析/语音合成"分组;音色区块列表+试听+上传
   - 依赖: 2, 3, 6

9. 测试收口 + 全量回归
   - 文件: tests/*
   - 预估行数: ~100（补测）
   - 验证点: pytest 全量绿;basedpyright/pyright 全量 0/0/0
   - 依赖: 1-8

10. MacBook 本机端到端验证
    - 文件: 无新改
    - 预估行数: 0
    - 验证点: install_tts_deps.sh 本机跑通;模型 rsync 到 $OPENSECURITY_HOME/models/cosyvoice3-8bit/;
      POST /api/tts（真模型）返回 WAV + atempo 生效 + 音色切换生效; voices 列表正确
    - 依赖: 1-9

11. MacMini 部署 + 远程验证
    - 文件: 无新改（git push + update-restart + rsync 模型 + 节点装依赖）
    - 预估行数: 0
    - 验证点: 节点 git 更新到目标 commit;模型目录就位;节点 worker 就绪
      （models-forward 状态 ready）;控制台 should_use_remote 路径 POST /api/tts
      返回节点合成的 WAV;内存峰值 < 4.5GB（节点 soak 20 段）
    - 依赖: 10

12. 台账收口（progress.md + architecture-map 若需）
    - 验证点: 台账含全部迭代与教训
    - 依赖: 11
```

## §4 验收标准

**功能验收**:
- POST /api/tts {text, voice: "official_female", speed: 0.9} → WAV（24kHz PCM16）时长合理;speed=1.0 无 atempo
- GET /api/tts/voices 返回官方女声;上传新音色后列表+1;无 DELETE 端点
- 音色切换: 不同 voice id 输出不同音色（听感区分）
- 静音输出自动重试（mock 尾部静音 → 第二次正常）
- 远程路径: 控制台 → MacMini P2P → WAV 回传
- --model-tags security 不装 TTS;security,tts 装;skip_tts 参数消失

**回归验收**:
- pytest 全量绿（含既有 58+ 用例）;pyright/basedpyright 0/0/0
- embed/rerank/ocr 远程链路不受影响（MCP 冒烟）
- Kokoro 业务代码零残留（grep 断言）

**架构验收**:
- 单向依赖无破坏（voice_library 不 import routes;worker 独立进程）
- 模型 tags 通用设计: 新增一个假想 tag 的模型条目只需声明（无需改 ensure_models）
- worker 内存纪律: 连续 20 段合成 RSS 稳定（无累积增长）

## §5 与现有需求文档的关系

- 承接《2026-10-10-remote-p2p-transport》的远程推理框架（should_use_remote/tts_synth/P2P 通道复用）
- Kokoro 相关设计（TtsAsset 目录模式/GitHub worker 模式）作为模式参考被 CosyVoice3Asset 继承，实体退役
