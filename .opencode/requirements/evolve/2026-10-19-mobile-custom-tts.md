# 手机端定制 TTS 引擎与混合朗读（remote-link 加固 + 配置界面 + 首段兜底）

> 目标仓库：`/Users/aserlili/Documents/Codes/legado-with-MD3`（Android，Kotlin/Compose）
> 服务端：OpenSecurity 控制台 TTS（`/api/tts`，CosyVoice3）
> 需求来源：用户需求文档《需求-手机APP连接TTS.md》（2026-10-19）

## §1 背景与目标

### 1.1 现状

手机端 APP（Legado 分支）已新增 `:modules:remote-link` 模块：在手机本机启动 HTTP 网关（默认 127.0.0.1:18888），把 Legado HttpTTS 引擎的 HTTP 请求经 P2P（TCP 信令 + UDP 打洞 / 中继兜底 + Noise NNpsk2 加密）转发到 MacMini 节点，节点调用 OpenSecurity 控制台的 TTS 服务合成音频。

当前链路的四个缺口：

1. **remote-link 质量未系统检查**：仅 1 个协议向量测试（7 用例），P2pClient 状态机 / 本地网关 / 负向路径无测试；存在 App 启动崩溃风险（非法 PSK、端口占用）、资源泄漏、客户端超时（30s）短于服务端 TTS 超时（90s）、网关参数仅 text/speed/voice。
2. **定制引擎/音色不是一等公民**：用户需手动新建 HttpTTS、手填 URL；服务端音色列表（`/api/tts/voices`）无法在手机上浏览；无 instruct/seed/mode 参数；无试听；无独立配置界面。
3. **无兜底与混合朗读**：远程服务不可用/变慢时，朗读只有"静默音频/暂停"；无首段兜底、无段级无缝切换、无切换提示。
4. **非 UI 逻辑测试不足**：上述逻辑全部依赖真机安装与人工试听验证。

### 1.2 目标

| 编号 | 目标 | 验收锚点 |
|---|---|---|
| G1 | remote-link 功能有效、异常/超时/断连稳定 | §4 功能验收 1-3 |
| G2 | 定制引擎/音色可在手机端配置、试听、播放 | §4 功能验收 4-11 |
| G3 | 混合朗读：首段兜底、段级无缝切换、远端恢复自动切回 | §4 功能验收 12-17 |
| G4 | 非 UI 逻辑通过本地自动化测试充分验证 | §4 测试验收 |

### 1.3 关键设计决策（已与用户确认）

1. **复用 HttpTTS 播放链路**：remote-link 的本地网关对 Legado 暴露 HTTP，Legado 以 HttpTTS 引擎接入；不改远端 wire protocol。
2. **模块职责**：`remote-link` 保留（传输层：P2P/加密/网关/连接配置）；新增 `:modules:custom-tts`（业务层：参数模型、分段器、混合策略，纯逻辑可单测）。两者互不依赖，app 同时依赖。
3. **分段算法整体复用**：PC 前端 `segmentText.ts` 的分段器（首段 20 字 + 20→40→60→80 阶梯 + 句末切分 + 尾并回）Kotlin 移植进 `custom-tts`，用 TS 生成一致性测试向量；首段字数可配置，阶梯序列可配置。
4. **兜底按段粒度、永不等待、不锁定**：每段播放前判定远程音频是否就绪——就绪用远程，未就绪立即用兜底（远端请求继续在途）；后续段重复判定；远端恢复后自然切回。首段兜底开关关闭 = 首段不强制兜底（若远程未就绪，仍按普通规则降级兜底）。
5. **兜底引擎范围**：任意已配置引擎（系统 TTS / HttpTTS / 云 TTS），排除定制远程引擎本身；兜底音色随引擎选择。
6. **速度分开设置**：配置页提供"兜底 TTS 速度"与"定制 TTS 速度"两个独立设置；APP 现有全局语速（ExoPlayer 播放端倍速）继续对两种音频统一生效。混合模式下这两个值覆盖音色级速度；非混合模式使用音色自身的速度参数（见 §2.3.2 优先级）。
7. **首段字数即分段阶梯首值**：首段兜底块 = 分段器产出的第一段；"首段字数"输入框直接编辑阶梯序列首值（默认 20）；修改后：默认阶梯自动重算，自定义阶梯仅更新首档并保留其余档位。
8. **一次交付**：A（remote-link 加固）、B（定制引擎/音色 + 配置界面）、C（混合朗读）、D（测试收口）同属本需求，按依赖顺序实施。

### 1.4 不在范围

- 手机端上传新音色（服务端上传端点保留，手机端不提供入口）。
- 服务端 `/api/tts` 参数扩展（现有 text/voice/speed/instruct/seed/mode 已覆盖）。
- 修改 P2P wire protocol 或 relayd。
- 多播报人（角色配音）与混合朗读的深度结合：混合模式下使用定制引擎默认音色 + 兜底音色，不启用角色路由（见 §2.6.1）。

## §2 技术方案

### 2.1 总体架构

```
┌────────────────────────── 手机 APP（legado-with-MD3） ──────────────────────────┐
│                                                                                │
│  feature/customtts（新 UI）                                                     │
│    配置页：连接 / 音色 / 参数 / 试听 / 混合朗读 / 分段设置                        │
│         │                                                                      │
│  CloudTtsScreen（「朗读引擎与音色」页）——新增"定制引擎"分组与入口                │
│         │                                                                      │
│  HttpReadAloudService（朗读播放：分段、进度、缓存、预合成）                       │
│         │         ▲                                                            │
│         │         │ 段级决策                                                    │
│         │   HybridSynthesisCoordinator（混合调度，app 内可单测）                  │
│         │                                                                      │
│  ┌──────▼──────────────┐          ┌──────────────────────────┐                 │
│  │ :modules:custom-tts  │          │ :modules:remote-link      │                 │
│  │ 纯逻辑（无 Android）  │          │ 传输层                    │                 │
│  │ · Segmenter          │          │ · P2pClient（P2P/加密）    │                 │
│  │ · HybridTtsPolicy    │          │ · LocalTtsGateway（HTTP）  │                 │
│  │ · 参数模型/请求构造   │          │ · ConfigStore             │                 │
│  └──────────────────────┘          └───────────┬──────────────┘                 │
│                                                │ P2P（TCP 信令 + UDP 打洞/中继）│
└────────────────────────────────────────────────┼────────────────────────────────┘
                                                 ▼
                                   MacMini 节点 → OpenSecurity TTS（CosyVoice3）
```

依赖方向：`app → custom-tts`、`app → remote-link`；`custom-tts` 与 `remote-link` 互不依赖。

### 2.2 remote-link 质量加固（A）

#### 2.2.1 问题清单与修复

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| A1 | `ConfigStore.configured()` | 非法 base64 PSK 时 `Base64.decode` 抛异常，`RemoteLinkManager.init` 在 `App.onCreate` 调用 → **启动崩溃** | `runCatching` 包裹，非法/长度≠32 一律返回 false |
| A2 | `RemoteLinkManager.startInternal()` | `LocalTtsGateway.start()` 端口占用抛 IOException → **启动崩溃** | try/catch；失败记录 `lastError` 且保持停止态，不抛出 |
| A3 | `RemoteLinkManager.stop()` / `P2pClient` | 只置空引用，socket 未关闭 → 资源泄漏 | `P2pClient.close()`（关闭 udp/relay 会话 + 标记 closed）；`stop()` 调用 |
| A4 | `P2pClient.apiTimeoutMs` | 默认 30s < 服务端 TTS 90s → 客户端先放弃、服务端白跑 | 默认 95s；新增请求级参数 `request(..., timeoutMs)`（混合调度用 10s） |
| A5 | `LocalTtsGateway.handleTts` | 仅 text/speed/voice；voice 默认写死 `zf_xiaobei` | 支持 voice/instruct/seed/mode；voice 缺省传空串（走服务端默认音色） |
| A6 | `LocalTtsGateway` | 无 `/voices` 路由、仅 POST | 新增 `GET /voices` → `client.request("GET", "/api/tts/voices", null)` 透传 JSON |
| A7 | `P2pClient` | 会话失效靠 socket 未关闭判断；无关闭方法 | `alive` 保持；`close()` + `isClosed`；请求异常时 dropSession（现有行为保留） |
| A8 | 测试/CI | 仅向量测试；CI 未跑该模块 | 新增 8 类测试（见 2.2.3）；CI 加入 `:modules:remote-link:testDebugUnitTest` |

#### 2.2.2 测试 seam（最小侵入）

```kotlin
// remote-link 新增接口，LocalTtsGateway 依赖抽象而非具体类
interface TtsClient {
    fun request(
        method: String, path: String, body: Map<String, Any?>?, token: String = "",
        timeoutMs: Int = DEFAULT_API_TIMEOUT_MS,
    ): Triple<Int, String, Any?>
    fun ping(): Boolean
    fun close()

    companion object { const val DEFAULT_API_TIMEOUT_MS = 95_000 }
}

class P2pClient(...) : TtsClient   // 现有 request 签名增加 timeoutMs（token 已在）

// 测试可注入：默认实现 = 原打洞/中继逻辑
class P2pClient @JvmOverloads constructor(
    ...,
    private val sessionFactory: SessionFactory? = null,  // internal 测试注入
)
fun interface SessionFactory { fun create(): Session }
```

`LocalTtsGateway` 的 query 解析抽为纯函数，便于单测：

```kotlin
data class GatewayTtsParams(
    val text: String, val speed: Double, val voice: String,
    val instruct: String, val seed: Int, val mode: String,
    val timeoutMs: Int? = null,  // 请求级超时（毫秒; 网关专用，不透传服务端）
)
object GatewayParams {
    fun parse(parameters: Map<String, List<String>>): Result<GatewayTtsParams>
    // JSONObject 构造（复用 remote-link 现有 org.json 依赖；禁止手写 JSON 转义）
    fun toJson(p: GatewayTtsParams): String
}
```

#### 2.2.3 测试清单（remote-link）

| 测试类 | 覆盖 |
|---|---|
| `SessionCryptoTest` | UDP 解密、重复计数器拒绝、TCP 序列号连续/跳号、错误密钥失败 |
| `NoiseHandshakeTest` | 错误 PSK、截断消息、乱序调用、重复消息、`split()` 前调用失败 |
| `FrameCodecTest` | 空 payload、最大帧、超限拒绝、一次 feed 多帧、半帧累积 |
| `FragmenterReassemblerTest` | 900 字节边界、256 片上限、缺片 `missing()`、重复片幂等、total 非法 |
| `MsgTest` | null/Boolean/Int/Long/Float/Double/Binary、嵌套 Map/List、非 map 输入拒绝 |
| `P2pClientTest` | 注入 fake SessionFactory：会话复用、失效重建、打洞失败落中继、响应乱序按 id 匹配、请求超时、close 后拒绝 |
| `LocalTtsGatewayTest` | 注入 fake TtsClient：参数解析（含中文 instruct/seed 边界/mode）、缺 text、状态码映射、非音频响应、`/voices` 透传、`/health` |
| `ConfigStoreTest` | Robolectric：默认值、非法 PSK → configured()=false、读写往返 |

新增测试依赖：`testImplementation("org.robolectric:robolectric:<app 模块同版本>")`、`testImplementation("androidx.test:core:<app 模块同版本>")`——版本一律以 `gradle/libs.versions.toml` / app 模块现有依赖为准，不臆造版本号。

### 2.3 custom-tts 模块（B/C 的逻辑基座）

#### 2.3.1 模块形态

- 路径：`modules/custom-tts/`；Gradle path `:modules:custom-tts`；包名 `com.opensecurity.customtts`。
- 插件：`alias(libs.plugins.android.library)`（与 remote-link 一致，便于构建配置统一；模块内不引用 Android API）。
- 依赖：`implementation(libs.gson)` 仅用于 JSON 编解码边界（项目已有 GSON，无需新增 serialization 插件）；`testImplementation("junit:junit:4.13.2")`。
- `settings.gradle` 增加 `include ':modules:custom-tts'`；`app/build.gradle.kts` 增加 `implementation(project(":modules:custom-tts"))`。

#### 2.3.2 数据类型（强类型，禁止裸 dict）

```kotlin
/** 定制引擎的合成参数（对应服务端 /api/tts 请求体）。 */
data class CustomTtsVoiceParams(
    val voiceId: String = "",          // 空=服务端默认音色
    val speed: Float = 1.0f,           // 0.5..3.0
    val instruct: String = "",         // ≤200 字
    val seed: Int = -1,                // -1=默认；0..99999 合法
    val mode: String = "",             // ""=zero_shot；"instruct"=指令控制
)

/** 分段单元（偏移量用于进度/高亮映射）。 */
data class CustomTtsSegment(
    val text: String,
    val startOffset: Int,              // 章节朗读文本流中的起始字符偏移（含）
    val endOffset: Int,                // 结束偏移（不含）
)

/**
 * 混合朗读配置（引擎/音色引用使用稳定字符串 ID，由 app 层解释）。
 * 速度语义（优先级从高到低）：
 *   混合模式: fallbackSpeed / customSpeed（本配置）覆盖音色级速度
 *   非混合模式: CustomTtsVoiceParams.speed（音色级）生效，本配置的速度字段不参与
 * 首段字数不在此配置：首段兜底块 = 分段器第一段，字数由 CustomTtsSettings.segmentStairs[0] 决定。
 */
data class HybridTtsConfig(
    val firstSegmentFallback: Boolean = true,
    val remoteTimeoutMs: Int = 10_000, // 单段远程请求超时
    val fallbackEngineType: String = "system",
    val fallbackEngineId: String = "",
    val fallbackSpeakerId: String = "",
    val fallbackSpeed: Float = 1.0f,   // 兜底引擎合成速度（混合模式）
    val customSpeed: Float = 1.0f,     // 定制引擎合成速度（混合模式）
)

/** 段级决策结果。 */
enum class HybridTtsDecision { Remote, Fallback }

/** 切换事件（供 UI Toast；防抖由策略内完成）。 */
enum class HybridTtsSwitch { ToFallback, ToRemote }

/** 服务端音色目录条目（/api/tts/voices 响应的解析模型）。 */
data class CustomTtsVoiceEntry(
    val id: String,
    val name: String,
    val gender: String = "",
    val description: String = "",
    val isDefault: Boolean = false,
    val available: Boolean = true,
)
```

#### 2.3.3 分段器（移植 PC 前端 `segmentText.ts`）

`object Segmenter` 公开 API：

```kotlin
object Segmenter {
    const val DEFAULT_FIRST_LEN = 20
    const val DEFAULT_NEXT_LEN = 80

    /** 句块切分（句末标点；小数点防误切；闭引号并入）。 */
    fun splitSentences(text: String): List<String>

    /** 首段长度 → 阶梯序列（20→40→60→80 封顶 target）。 */
    fun rampFor(firstLen: Int, target: Int = DEFAULT_NEXT_LEN): List<Int>

    /** 阶梯序列规范化（正整数、≤8 档、升序去重；非法回 null）。 */
    fun normalizeStairs(input: List<Int>?): List<Int>?

    /** 全量分段（与 TS 版逐段一致）。 */
    fun segmentText(
        text: String,
        target: Int = DEFAULT_NEXT_LEN,
        hardMax: Int = 0,
        firstTargets: List<Int> = rampFor(DEFAULT_FIRST_LEN, target),
    ): List<String>

    /** 带偏移的分段（本章朗读文本流）。 */
    fun segmentWithOffsets(
        text: String,
        target: Int = DEFAULT_NEXT_LEN,
        hardMax: Int = 0,
        firstTargets: List<Int> = rampFor(DEFAULT_FIRST_LEN, target),
    ): List<CustomTtsSegment>
}
```

移植规则（与 TS 版逐字符对齐）：

| 规则 | 说明 |
|---|---|
| 句末断点 | `。！？…!?`、换行、英文 `.`（前后皆数字时跳过） |
| 收尾并入 | 句末符后的连续句末符与闭引号 `”’」』）)》` 并入当前句（只含闭引号，不含开引号） |
| 软断点 | `，、；：,;:`（数字间隙防误切） |
| 贪心合并 | 当前段 ≥ 目标长即收段 |
| 预检收段 | 当前段 ≥ 半目标且吞下句 >150% 目标时先收 |
| 超限守门 | 软限 = 目标+首段；硬限 = 首段×2+目标；软标点断 / 硬切兜底 |
| 首句长切 | 首句 > 首段目标×1.5 时在 ≥目标的逗号/分号处断 |
| 超长句 | > max(target×1.5,120) 在逗号/顿号切 ≤ 硬限/2 的片 |
| 尾段并回 | 尾段 < 首段目标且合并后 ≤ max(target×2,160) 时并入前段 |

一致性验证：用 Node 执行 TS 版 `segmentText` 生成 `vectors-segmenter.json`（输入文本 → 期望段数组），Kotlin 测试逐段断言一致。测试向量至少覆盖：

1. 默认 98 字短文（首段 20）；
2. 长文（>500 字，验证阶梯 20/40/60/80）；
3. 长首句（>30 字无句号，验证逗号切分）；
4. 超长句（>200 字，验证硬切）；
5. 纯短句（每句 2 字，验证合并）；
6. 短尾段（验证并回）；
7. 跨自然段（文本含换行，验证跨段累计）；
8. 空文本/纯空白（返回空列表）；
9. 首段字数 5/30/60（验证 ramp 变化）；
10. 自定义阶梯 `[30,60,80]`。

#### 2.3.4 混合策略状态机

```kotlin
/**
 * 段级赛跑决策（纯逻辑，无协程/无 IO）。
 * 语义：每段播放前判定远程是否就绪；未就绪用兜底，远程请求继续在途；
 * 远端恢复后下一段自然切回；切换事件防抖（默认 5s 内同方向只报一次）。
 */
class HybridTtsPolicy(
    private val config: HybridTtsConfig,
    private val switchDebounceMs: Long = 5_000,
) {
    fun decide(segmentIndex: Int, remoteReady: Boolean): HybridTtsDecision
    fun onRemoteResult(segmentIndex: Int, success: Boolean)  // 记录结果
    fun onSegmentPlayed(segmentIndex: Int, decision: HybridTtsDecision)
    fun drainSwitchEvents(nowMs: Long): List<HybridTtsSwitch>
    fun reset()
}
```

规则：

1. `segmentIndex == 0 && config.firstSegmentFallback` → 强制 `Fallback`（首段兜底）；
2. 其他段：`remoteReady == true` → `Remote`；否则 `Fallback`；
3. `remoteReady` 由协调器根据该段远程请求状态提供（Ready=true；Pending/Failed=false）；
4. 远程由不可用恢复为可用时产生 `ToRemote` 事件；由可用变为不可用时产生 `ToFallback` 事件（同方向 5s 防抖）；
5. 不锁定：每次 `decide` 独立判定，无"已切兜底"永久状态。

### 2.4 定制引擎/音色数据模型与存储

#### 2.4.1 引擎与音色建模（复用 Legado 现有体系）

| 概念 | 建模 | 存储 |
|---|---|---|
| 定制引擎 | 1 条 `HttpTTS`（固定 id，name="定制朗读引擎"） | `httpTTS` 表（现有 DAO） |
| 定制音色 | N 条 `ReadAloudVoice`（engineType=`ENGINE_HTTP`，engineId=HttpTTS.id，speakerId=服务端 voice_id，traitsJson=CustomTtsVoiceParams JSON） | `read_aloud_voices` 表（现有 DAO） |
| 连接配置 | relay host/port/PSK/nodeId/localPort/enabled | `ConfigStore`（remote-link，SharedPreferences `remote_link`） |
| 定制配置 | 默认音色、音色参数列表、混合配置、分段设置 | 新增 `CustomTtsSettingsGateway` + `CustomTtsSettingsRepository`（独立 JSON 文件 `filesDir/custom_tts_settings.json`，GSON 序列化；损坏/缺字段逐项回退默认） |

`CustomTtsSettings`（app 领域模型）：

```kotlin
data class CustomTtsSettings(
    val defaultVoiceId: String = "",           // 服务端 voice_id
    val voices: Map<String, CustomTtsVoiceParams> = emptyMap(),  // key=voice_id
    val hybrid: HybridTtsConfig = HybridTtsConfig(),
    val segmentTarget: Int = 80,               // 常规段目标
    val segmentStairs: List<Int> = listOf(20, 40, 60, 80), // 阶梯序列（首段字数=stairs[0]）
)
```

- **首段字数唯一来源**：`segmentStairs[0]`（默认 20，范围 5..200）。UI 的"首段字数"输入框编辑该值；未自定义阶梯时按 `rampFor(首段字数, segmentTarget)` 自动生成；自定义阶梯时只替换 `stairs[0]` 并保留其余档位（保持升序校验）。
- **速度唯一来源**：混合模式用 `hybrid.fallbackSpeed` / `hybrid.customSpeed`；非混合模式用 `voices[voiceId].speed`。两处不叠加。
- **混合启用条件**：选择定制引擎朗读且 `hybrid.fallbackEngineId` 非空时启用混合调度；未选择兜底引擎时按普通 HttpTTS 路径朗读（不启用兜底）。
- **可用性为派生状态**（无独立业务开关）：定制引擎条目"可用" = `ConfigStore.enabled` 且配置完整（PSK/地址/节点）；不可用时条目置灰、播放回退系统 TTS。
- **网关未启用**：`ReadAloud.getReadAloudClass()` 在定制引擎被选中但 `RemoteLinkManager.currentPort == 0` 时回退系统 TTS。
- **音色删除策略**：从设置中移除音色时，若该 `ReadAloudVoice` 已被 `book_voice_bindings` 引用，则置 `enabled=false` 而非物理删除；未被引用才删除。

- `CustomTtsSettingsGateway` 接口 + `CustomTtsSettingsRepository` 实现（GSON），提供 `settings: StateFlow<CustomTtsSettings>` 与 `update { copy(...) }`（遵循项目设置边界规则，原子提交）。
- 引擎 HttpTTS 同步：保存配置时 upsert：
  - `name = "定制朗读引擎"`
  - `url = "http://127.0.0.1:<localPort>/tts?text={{speakText}}"`（**不含 `{{speakSpeed}}`**：定制/混合速度由 voice traits 以 0.5..3.0 服务端语义追加，避免与 0..80 刻度冲突）
  - `contentType = "audio/.*"`（宽松匹配，服务端返回 audio/wav）
  - `speed` 保持默认 5（该字段在定制路径不参与合成）
- 音色同步：保存时对 `settings.voices` 逐项 upsert `ReadAloudVoice`（`managedBy=MANAGED_BY_CONFIGURED_TTS`）；已移除的音色按"删除策略"处理（被 `book_voice_bindings` 引用则禁用，否则删除）。
- 音色目录拉取：`GET /api/tts/voices`（经本地网关）→ app 层解析为 `CustomTtsVoiceEntry`（id/name/gender/description/isDefault/available）。解析结果仅用于配置页展示，不持久化目录本身。

#### 2.4.2 HttpReadAloudService 的 voice 参数覆盖

现有 Http 合成路径只使用 `httpTts.url` + `speakText` + `speakSpeed`。定制音色需要在合成时注入 traits 参数：

```kotlin
// 纯函数（help/readaloud/playback/CustomTtsUrlBuilder.kt）
// 输入：定制引擎 URL 模板（含 {{speakText}}）
// 步骤：① 展开 {{speakText}}（URL 编码）
//       ② 追加 voice/speed/instruct/seed/mode（URL 编码；speed 为 0.5..3.0 服务端语义）
//       ③ 输出最终 URL（不含模板变量）交给 AnalyzeUrl 请求
fun buildCustomTtsUrl(
    templateUrl: String, text: String, params: CustomTtsVoiceParams,
): String
```

- 判定：`routedVoice.engineType == ENGINE_HTTP && routedVoice.engineId == 定制引擎 id`
- 速度注入：`params.speed`（混合模式下替换为 `hybrid.customSpeed`）→ 网关 `speed` 参数 → 服务端。
- traitsJson 解析失败 → 按空参数（服务端默认）处理，不中断朗读。
- **缓存键必须含参数**：`sourceKeyForCue` 的定制引擎分支返回 `"custom:<voiceId>:<paramsHash>"`（参数变化必须产生新缓存键，避免播放到旧参数的音频）。
- 非定制 HttpTTS 引擎路径保持现状（零改动）。

### 2.5 配置界面（B）

#### 2.5.1 导航与页面结构

- 新增路由：`MainRouteCustomTtsEngine(bookUrl: String? = null)`（`MainNavKey.kt`）。
- 新增 Feature 包：`app/src/main/java/io/legado/app/feature/customtts/`：
  - `CustomTtsContract.kt`（UiState/Intent/Effect）
  - `CustomTtsViewModel.kt`
  - `CustomTtsRouteScreen.kt`（Koin ViewModel + 导航回调）
  - `CustomTtsScreen.kt`（无状态 Screen）
  - `components/`（分组卡片、音色行、参数 BottomSheet）
- DI：`appModule.kt` 注册 `viewModelOf(::CustomTtsViewModel)` 与 Settings Store 绑定。
- `MainNavGraph.kt` 增加 entry；`CloudTtsScreen` 的"定制引擎"分组入口导航到此页。

页面布局（小屏，LazyColumn 分组卡片）：

| 分组 | 内容 |
|---|---|
| 连接 | 中继地址、端口、PSK、节点 ID、本地网关端口、启用开关、"测试连接"按钮（显示状态：未配置/连接中/已连通/失败原因） |
| 音色 | 从服务端拉取的音色列表（名称/性别/描述/默认标记/可用性）；"刷新目录"按钮；不可用音色置灰并标注；每行可编辑参数（BottomSheet：speed/instruct/seed/mode）、设为默认、启用/停用；目录拉取失败时提供"手动输入 voice_id"兜底入口 |
| 参数编辑 | `speed` 滑杆（0.5..3.0）；`instruct` 预设下拉（与 PC 前端相同的官方/实测预设）+ 自定义输入（≤200 字）；`seed` 数字输入（留空=-1，范围 -1..99999）；`mode` 二选一（默认 zero_shot / 指令控制） |
| 试听 | 当前选中音色 + "试听"按钮（合成固定示例文本并播放；失败 Toast 原因） |
| 混合朗读 | 首段兜底开关（默认开）、兜底引擎选择（系统/HTTP/云，排除定制引擎）、兜底音色选择、兜底速度、定制速度、远程超时（高级，默认 10s）；分组顶部说明"与角色配音互斥"（混合模式使用默认音色 + 兜底音色） |
| 分段设置 | 首段字数输入框（默认 20，编辑 `segmentStairs[0]`）、阶梯序列输入（如 `20,40,60,80`）+ 预设（20/30/60 起）、常规段目标（默认 80）；修改首段字数且未自定义阶梯时自动重算阶梯 |
| 保存 | 底部保存按钮（校验 + 应用 + Toast） |

**旧入口处理**：现有 `remote-link` 的 `ConfigActivity`（设置页入口）保留，作为连接配置的兼容入口；两处修改同一 `ConfigStore`，保存后均调用 `RemoteLinkManager.restart()`。新配置页不再重复实现连接表单之外的传输逻辑。

#### 2.5.2 交互与校验

| 项 | 校验/行为 |
|---|---|
| PSK | Base64 且解码后 32 字节；非法行内错误提示，不崩溃 |
| 端口 | 1..65535 |
| 首段字数 | 5..200 整数 |
| 阶梯序列 | 正整数、≤8 档、升序；非法时回退默认 |
| 速度 | 定制速度 0.5..3.0（直接作为服务端 speed）；兜底速度倍速 v：系统 TTS → `speechRate = v`、云 → `speed = v`、HTTP → 换算 Legado 刻度 `speakSpeed = round(v * 10 - 5)`（与 `(speakSpeed+5)/10` 互逆）；UI 显示倍速（一位小数） |
| 保存 | 先校验连接可解析；写 Settings → 同步 HttpTTS/音色 → `RemoteLinkManager.restart` → Toast 结果 |
| 未启用网关 | 音色拉取/试听按钮禁用并提示"先启用连接" |
| 混合模式提示 | 分组内固定说明："混合朗读使用默认音色 + 兜底音色；角色配音在此模式下不生效" |

#### 2.5.3 试听链路

```
点击试听 → ViewModel 构造示例文本 + 当前音色参数
 → OkHttp GET http://127.0.0.1:<localPort>/tts
     参数由 OkHttp HttpUrl.Builder 编码（text/voice/speed/instruct/seed/mode）
 → 网关 → P2P → 服务端合成 → 音频字节
 → 写入 cacheDir/custom_tts_preview/<hash>.wav
 → CustomTtsEffect.PlayPreview(path) → Screen 的 MediaPlayer 播放（复用 CloudTtsScreen 的 PlayPreview 模式）
```

失败分支：连接失败/超时/非 200/响应非音频 → `ShowToast(具体原因)`，不崩溃。

### 2.6 混合朗读（C）

#### 2.6.1 分段单元与原有 cue 的关系

- **启用条件**：朗读引擎为定制引擎，且 `CustomTtsSettings.hybrid.fallbackEngineId` 非空。其他引擎或未配置兜底时完全保持现有逻辑。
- **文本流来源**：与现有 `contentList` 相同的解析结果——`readAloudChapter.paragraphs(splitByPage, splitPolicy)` 的段落文本按现有拼接规则连成单一文本流（`AppPattern.notReadAloudRegex` 清理前）；`segmentWithOffsets` 的偏移以该文本流为基准。已知交付差异：混合模式不朗读章节标题（标题单元独立坐标系，见 progress 记录）。
- **进度/高亮**：`readAloudNumber = 章节绝对位置(segment.startOffset + 段内偏移)`，换算复用现有 `paragraphChapterPositionAt` 逻辑；章节内字符位置口径与现有进度一致。
- **多播报人**：混合模式 v1 使用"定制引擎默认音色 + 兜底音色"，不启用角色路由（`useMultiSpeaker` 在混合模式下视为 false）；UI 固定提示（§2.5.1），不静默改变书内绑定。

#### 2.6.2 HybridSynthesisCoordinator（app 内纯逻辑 + 协程）

```kotlin
class HybridSynthesisCoordinator(
    private val scope: CoroutineScope,
    private val remoteSynth: suspend (segment: CustomTtsSegment, params: CustomTtsVoiceParams) -> File?,   // 写文件
    private val fallbackSynth: suspend (segment: CustomTtsSegment, speedOverride: Float) -> File?,         // 引擎/音色由 app 闭包捕获
    private val policy: HybridTtsPolicy,
    private val config: HybridTtsConfig,
    private val onSwitch: (HybridTtsSwitch) -> Unit,
) {
    fun start(segments: List<CustomTtsSegment>)
    suspend fun audioFor(index: Int): File?   // 播放前调用：返回就绪的远程文件或兜底文件
    fun stop()
}
```

调度规则：

1. 每段播放前调度该段及后 2 段（返回驱动）的远程请求与兜底预合成；合成在 IO 调度器执行（阻塞读不落主线程），远程单段超时 10s（含网关请求级超时透传）；
2. `audioFor(i)`：
   - 远程结果就绪 → 返回远程文件；
   - 否则等待该段兜底文件（兜底预合成通常 <1s；若未完成则等待其完成，但不超过兜底引擎自身超时）；
   - 兜底也失败 → 返回 null（调用方使用无声文件 `createSilentSound`）；
   - 返回后立即触发 i+1、i+2 的预取（返回驱动）；
3. 远程请求超时（`remoteTimeoutMs`）→ 标记该段 Failed 并取消请求；**晚到结果**：若请求在取消前已完成，写入缓存供重听命中，但不用于已播放段；
4. 远程成功/失败状态变化 → `policy.onRemoteResult` → 切换事件 → Toast（防抖）；
5. 暂停/停止：取消在途请求与预合成；恢复时从当前段重建窗口（已缓存文件直接命中）；
6. 翻章：取消旧章节任务，按新章节重建。

#### 2.6.3 HttpReadAloudService 集成

- `play()` 分支：`if (isCustomHybridMode) playCustomHybrid() else 现有逻辑`。
- `playCustomHybrid()`：
  - 构建 segments（缓存于当前章节）；
  - `coordinator.start(segments)`；
  - 循环 `i`：`audioFor(i)` → `ExoPlayer.setMediaItem/addMediaItem` → 播放；
  - `onMediaItemTransition` / `STATE_ENDED` → 更新进度（按 segment.startOffset）；
  - 段落间隔、缓存清理沿用现有设置；跨章预下载（`audioPreDownloadNum`）在混合模式下不启用（段级协调器窗口天然流式，不重复预合成）；非混合路径预下载不变。
- 缓存文件名：
  - 远程：`md5(chapterTitle + segment.text + paramsHash)`
  - 兜底：`md5(chapterTitle + segment.text + fallbackEngineId + fallbackSpeakerId)`
  - 文件名前缀沿用现有 `md5SpeakFileName` 的章节标题前缀，保证现有缓存清理逻辑兼容。
- 兜底合成：抽 `interface FallbackSynthesizer { suspend fun synthesize(segment: CustomTtsSegment, engineRef: EngineRef, speedOverride: Float, output: File): Boolean }`，按兜底引擎类型分派现有合成器（`SystemTtsFileSynthesizer` / `CloudTtsAudioSynthesizer` / HTTP `getSpeakStream`），`speedOverride` 覆盖音色级速度。
- `getSpeakStream` 扩展两处可选参数（默认值 → 原行为）：
  - `voiceParams: CustomTtsVoiceParams? = null`（定制引擎参数覆盖）；
  - `speakSpeedOverride: Int? = null`（HTTP 兜底引擎的速度覆盖，Legado 刻度 0..80，由 §2.5.2 换算）。
  - 调用方 4 处（`downloadAndPlayAudios` / `synthesizeSingleCue` / `createDataSourceFactory` / 流式预合成）同步传入；非定制/非兜底路径传 null。
- 失败兜底链：兜底引擎也失败 → 无声文件（现有 `createSilentSound`），不中断章节。
- Toast：`onSwitch` → `toastOnUi("已切换为兜底引擎")` / `toastOnUi("已恢复定制引擎")`。

### 2.7 架构影响

| 层 | 变化 |
|---|---|
| Gradle | 新增 `:modules:custom-tts`；`:app` 增加依赖；CI 增加两个模块的测试任务 |
| app UI | 新增 `feature/customtts` 包；`CloudTtsScreen` 增加一个分组与入口；`MainNavGraph` 增加一个路由 |
| app 服务 | `HttpReadAloudService` 增加混合模式分支（非混合路径零改动） |
| app 数据 | 新增 `CustomTtsSettingsRepository`（独立 JSON 文件 `filesDir/custom_tts_settings.json`，GSON）；复用 `httpTTS` / `read_aloud_voices` 表（无 DB 迁移） |
| remote-link | API 扩展（`TtsClient` 接口、`close()`、请求级超时、网关参数/`/voices`）；不改变 wire protocol |
| custom-tts | 全新模块（纯逻辑） |

**不引入数据库迁移**（复用现有表），降低升级风险。

### 2.8 错误与降级矩阵

| 场景 | 行为 |
|---|---|
| PSK 非法 / 端口占用 | App 正常启动；配置页显示"网关未运行/错误原因" |
| 网关未启用 / 未配置 | 定制引擎条目不可用；播放时若被选中 → 回退系统 TTS（现有 `ReadAloud` 逻辑） |
| 远程请求超时（单段） | 该段用兜底；远程继续下一段请求；Toast 防抖 |
| 远程连续失败 | 后续段用兜底；远程每段仍重试（不锁定）；恢复后自动切回 |
| 兜底引擎失败 | 该段无声（现有 `createSilentSound`），不中断章节 |
| 音色目录拉取失败 | 配置页显示错误；保留手动输入音色 ID 的兜底入口 |
| traitsJson 损坏 | 按空参数合成（服务端默认音色），不崩溃 |
| 试听失败 | Toast 具体原因；不影响已保存配置 |
| 播放中服务端重启 | 当前段可能失败 → 兜底；下一段重新探测 |

## §3 实现规范

### 3.1 实施步骤

> 每步 ≤200 行（不含注释与空行）；每步完成后执行验证点；依赖前置步骤。
> 阶段顺序：A（remote-link）→ B（custom-tts）→ C（数据）→ D（UI）→ E（混合朗读）→ F（验收）。

#### 阶段 A：remote-link 质量加固

**步骤 1. 启动容错与资源释放**
- 文件：`modules/remote-link/.../gateway/LocalTtsGateway.kt`、`.../transport/P2pClient.kt`
- 内容：`ConfigStore.configured()` 的 Base64 解码包 `runCatching`；`RemoteLinkManager.startInternal()` 捕获 `start()` 异常并记录 `lastError`；`P2pClient` 新增 `close()`/`isClosed`；`RemoteLinkManager.stop()` 调用 `client.close()`。
- 预估行数：60
- 验证点：`./gradlew :modules:remote-link:compileDebugKotlin` 通过；`ConfigStore` 非法 PSK 单测返回 false；`P2pClient` close 后 `request` 抛异常。
- 依赖：无

**步骤 2. 请求级超时与默认值对齐**
- 文件：`P2pClient.kt`、`LocalTtsGateway.kt`
- 内容：`request(method, path, body, token, timeoutMs = DEFAULT_API_TIMEOUT_MS)`；`DEFAULT_API_TIMEOUT_MS = 95_000`；`ping()` 超时 5s 不变；网关调用使用默认超时。
- 预估行数：40
- 验证点：单测注入 fake session 验证 timeout 参数传递与超时异常消息。
- 依赖：步骤 1

**步骤 3. 测试 seam：TtsClient 接口**
- 文件：`P2pClient.kt`、`LocalTtsGateway.kt`
- 内容：新增 `interface TtsClient`；`P2pClient : TtsClient`；`LocalTtsGateway(port, client: TtsClient)`；`P2pClient` 增加 `@VisibleForTesting internal` 的 `SessionFactory` 注入点。
- 预估行数：50
- 验证点：`:modules:remote-link:compileDebugKotlin` 通过；现有调用方（`RemoteLinkManager`）签名兼容。
- 依赖：步骤 2

**步骤 4. 网关参数扩展（voice/instruct/seed/mode + /voices）**
- 文件：`LocalTtsGateway.kt`（新增 `GatewayParams`）
- 内容：纯函数 `parse(parameters)` / `toJson(params)`；`/tts` 支持 7 参数（text/speed/voice/instruct/seed/mode/timeout_ms）；新增 `GET /voices` 透传；`/health` 保持；错误映射（400/500/502）。
- 预估行数：120
- 验证点：`LocalTtsGatewayTest`（fake TtsClient）覆盖：参数完整/缺省、中文 instruct、seed=-1/0/99999、mode 空/instruct、`/voices` 返回 JSON、非音频响应。
- 依赖：步骤 3

**步骤 5A. 协议负向测试（加密与握手）**
- 文件：`src/test/.../crypto/SessionCryptoTest.kt`、`NoiseHandshakeTest.kt`
- 内容：SessionCrypto 解密/重放拒绝/序列号；Noise 错误 PSK/截断/乱序/重复消息。
- 预估行数：120
- 验证点：`./gradlew :modules:remote-link:testDebugUnitTest` 全绿。
- 依赖：无

**步骤 5B. 协议边界测试（帧/分片/消息）**
- 文件：`src/test/.../frame/FrameCodecTest.kt`、`FragmenterReassemblerTest.kt`、`MsgTest.kt`
- 内容：帧空/最大/超限/多帧；分片 900/256/缺片/重复；msgpack 类型与嵌套。
- 预估行数：160
- 验证点：`./gradlew :modules:remote-link:testDebugUnitTest` 全绿（含原有 7 个向量用例）。
- 依赖：无

**步骤 6A. P2pClient 状态机测试**
- 文件：`src/test/.../transport/P2pClientTest.kt`
- 内容：fake `SessionFactory`：会话复用/失效重建/打洞失败落中继/乱序响应按 id 匹配/请求超时/close 后拒绝。
- 预估行数：160
- 验证点：`./gradlew :modules:remote-link:testDebugUnitTest` 全绿。
- 依赖：步骤 3

**步骤 6B. 网关与配置存储测试**
- 文件：`LocalTtsGatewayTest.kt`、`ConfigStoreTest.kt`；`build.gradle.kts` 增加 Robolectric 依赖（版本以 app 模块 `libs.versions.toml` 为准）
- 内容：fake `TtsClient` 网关（参数/状态码/非音频/`/voices`/`/health`）；Robolectric ConfigStore（默认值/非法 PSK/读写往返）。
- 预估行数：180
- 验证点：`./gradlew :modules:remote-link:testDebugUnitTest` 全绿；总用例数 ≥ 35。
- 依赖：步骤 4

**步骤 7A. CI 接入（remote-link）**
- 文件：`.github/workflows/verify.yml`
- 内容：主验证集命令追加 `:modules:remote-link:testDebugUnitTest`。
- 预估行数：5
- 验证点：`git diff --check`；人工核对 YAML 缩进与任务名。
- 依赖：步骤 6B

**步骤 7B. CI 接入（custom-tts）**
- 文件：`.github/workflows/verify.yml`
- 内容：主验证集命令追加 `:modules:custom-tts:testDebugUnitTest`。
- 预估行数：5
- 验证点：`git diff --check`；`./gradlew :modules:custom-tts:testDebugUnitTest` 任务存在。
- 依赖：步骤 8

#### 阶段 B：custom-tts 模块

**步骤 8. 模块骨架**
- 文件：`modules/custom-tts/build.gradle.kts`、`settings.gradle`、`app/build.gradle.kts`
- 内容：Android library 模块（无 Android API）；包 `com.opensecurity.customtts`；junit + GSON 依赖（`libs.gson`）。
- 预估行数：40
- 验证点：`./gradlew :modules:custom-tts:compileDebugKotlin` 通过。
- 依赖：无

**步骤 9. 分段器基础原语**
- 文件：`segmenter/SentenceScanner.kt`（scanSentence/splitSentences）、`segmenter/SegmentMath.kt`（rampFor/normalizeStairs/splitOversize）
- 内容：按 §2.3.3 移植；纯函数无状态。
- 预估行数：150
- 验证点：本地单测覆盖句末/小数点/闭引号/空文本；Ramp 序列断言 `[20,40,60,80]`、`[30,60,80]`。
- 依赖：步骤 8

**步骤 10. 分段器主算法**
- 文件：`segmenter/Segmenter.kt`
- 内容：`segmentText` / `segmentWithOffsets`（贪心/预检/overflowCut/cutFirstComma/尾并回）。
- 预估行数：180
- 验证点：Node 生成的向量全通过（步骤 11 联合验证）。
- 依赖：步骤 9

**步骤 11. 分段器一致性测试向量**
- 文件：`modules/custom-tts/src/test/resources/vectors-segmenter.json`、`SegmenterTest.kt`
- 内容：Node 执行 `segmentText.ts` 生成 §2.3.3 的 10 组向量；Kotlin 逐段断言。生成脚本放临时目录（`/var/folders/.../opencode/` 下，不入库），向量文件入库；命令：`node --experimental-strip-types <script>.ts`（脚本通过相对路径 import 前端 `src/utils/segmentText.ts`）。
- 预估行数：120
- 验证点：`./gradlew :modules:custom-tts:testDebugUnitTest` 全绿；向量文件包含 10 组输入/期望输出。
- 依赖：步骤 10

**步骤 12. 参数模型与请求构造**
- 文件：`model/CustomTtsModels.kt`、`model/CustomTtsRequestBuilder.kt`
- 内容：`CustomTtsVoiceParams`/`CustomTtsSegment`/`HybridTtsConfig`；参数校验（speed/seed/instruct/mode）；JSON 序列化（服务端请求体）。
- 预估行数：120
- 验证点：单测覆盖合法/非法参数、序列化字段与 `/api/tts` 对齐。
- 依赖：步骤 8

**步骤 13. 混合策略状态机**
- 文件：`hybrid/HybridTtsPolicy.kt`
- 内容：按 §2.3.4 实现；事件防抖。
- 预估行数：120
- 验证点：单测覆盖首段兜底、就绪/未就绪、恢复切回、防抖、reset。
- 依赖：步骤 12

#### 阶段 C：数据与配置

**步骤 14. CustomTtsSettings 与 Store**
- 文件：`app/.../domain/model/settings/CustomTtsSettings.kt`、`domain/gateway/CustomTtsSettingsGateway.kt`、`data/repository/CustomTtsSettingsRepository.kt`（实现 Gateway）、`di/appModule.kt`
- 内容：设置模型 + StateFlow + `update { copy(...) }`；GSON 序列化；Koin 绑定。
- 预估行数：180
- 验证点：单测（序列化往返/默认值/非法 JSON 回退默认）；`verifyConfigArchitecture` 通过。
- 依赖：步骤 12

**步骤 15. 定制引擎/音色同步与音色目录**
- 文件：`app/.../data/repository/CustomTtsCatalogRepository.kt`、`domain/gateway/CustomTtsCatalogGateway.kt`、`di/appModule.kt`
- 内容：upsert HttpTTS（固定 id）+ ReadAloudVoice（traitsJson）；删除过期音色；`fetchVoices()` 经本地网关 GET `/voices` 并解析。
- 预估行数：180
- 验证点：纯逻辑测试（用 fake DAO/HTTP）；音色 JSON 解析（含缺字段/空列表/非法 JSON）。
- 依赖：步骤 14

**步骤 16. Http 合成参数覆盖**
- 文件：`app/.../help/readaloud/playback/CustomTtsUrlBuilder.kt`、`service/HttpReadAloudService.kt`
- 内容：`buildCustomTtsUrl(baseUrl, text, speed, params)` 纯函数；`getSpeakStream` 在定制引擎路径使用覆盖后的 URL；traits 解析容错。
- 预估行数：100
- 验证点：纯函数单测（中文 instruct URL 编码、seed/mode 传递、空参数回退原 URL）。
- 依赖：步骤 12

#### 阶段 D：配置界面

**步骤 17A. Feature 骨架（Contract/ViewModel/DI）**
- 文件：`feature/customtts/CustomTtsContract.kt`、`CustomTtsViewModel.kt`、`di/appModule.kt`、字符串资源
- 内容：UiState/Intent/Effect；ViewModel 依赖注入（Settings Store + Catalog Gateway）；Koin 注册；资源前缀 `feature_custom_tts_`。
- 预估行数：150
- 验证点：`:app:compileAppDebugKotlin` 通过。
- 依赖：步骤 14、15

**步骤 17B. 路由与 Screen 骨架**
- 文件：`ui/main/MainNavKey.kt`、`ui/main/MainNavGraph.kt`、`feature/customtts/CustomTtsRouteScreen.kt`、`CustomTtsScreen.kt`
- 内容：`MainRouteCustomTtsEngine` 路由 + entry + 空页面（AppScaffold/顶栏/返回）。
- 预估行数：120
- 验证点：`:app:compileAppDebugKotlin` 通过；导航入口在 `MainNavGraph` 注册（代码检查）。
- 依赖：步骤 17A

**步骤 18. 连接配置区块 + 测试连接**
- 文件：`feature/customtts/components/ConnectionSection.kt`、`CustomTtsViewModel.kt`
- 内容：表单 + 校验 + "测试连接"（OkHttp GET `/health`，5s 超时）+ 状态展示。
- 预估行数：180
- 验证点：ViewModel 单测（校验/状态流转，Robolectric）；非法输入不崩溃。
- 依赖：步骤 17B

**步骤 19. 音色列表与参数编辑**
- 文件：`feature/customtts/components/VoiceSection.kt`、`VoiceParamsSheet.kt`、`CustomTtsViewModel.kt`
- 内容：目录拉取、选择默认音色、参数 BottomSheet（speed/instruct/seed/mode）、启用/停用。
- 预估行数：200
- 验证点：ViewModel 单测（拉取成功/失败、参数校验、保存映射）；UI 预览（人工）。
- 依赖：步骤 18

**步骤 20. 试听**
- 文件：`feature/customtts/CustomTtsViewModel.kt`、`CustomTtsScreen.kt`
- 内容：构造请求 → OkHttp → 写缓存 → `PlayPreview` → MediaPlayer；错误提示。
- 预估行数：120
- 验证点：ViewModel 单测（成功/HTTP 错误/非音频/超时）；人工试听。
- 依赖：步骤 19

**步骤 21. 混合朗读与分段设置区块**
- 文件：`feature/customtts/components/HybridSection.kt`、`SegmentSection.kt`、`CustomTtsViewModel.kt`
- 内容：开关、首段字数（编辑 `segmentStairs[0]`）、兜底引擎/音色选择、双速度、超时、阶梯设置。引擎列表来源：系统引擎（`SystemTtsVoiceCatalog`）+ HTTP 引擎（`HttpTtsEngineGateway`）+ 云引擎（`CloudTtsEngineGateway`），排除定制引擎；音色列表随引擎类型联动。
- 预估行数：200（超出则按规则拆为"选择器"与"速度/分段"两步）
- 验证点：ViewModel 单测（引擎列表过滤/音色联动/校验/保存）；UI 预览。
- 依赖：步骤 20

**步骤 22. 「引擎与音色」页入口**
- 文件：`ui/book/readaloud/cloudtts/CloudTtsContract.kt`、`CloudTtsViewModel.kt`、`CloudTtsScreen.kt`、字符串资源
- 内容：新增"定制引擎"分组（展示定制引擎条目/状态/音色数）；新增"新增定制引擎"入口 → 导航到配置页。**新增逻辑必须消费 `CustomTtsCatalogGateway`，不得新增 `appDb`/DAO 直连**（CloudTtsViewModel 已有冻结的 DAO baseline）。
- 预估行数：150
- 验证点：`:app:compileAppDebugKotlin`；CloudTtsViewModel 单测（分组映射）；`verifyConfigArchitecture` 无新增违规。
- 依赖：步骤 21

#### 阶段 E：混合朗读

**步骤 23. 章节分段接入**
- 文件：`app/.../service/HttpReadAloudService.kt`、`app/.../domain/readaloud/CustomHybridChapter.kt`（或 helper）
- 内容：按 §2.6.1 的文本流来源构建文本流 → `Segmenter.segmentWithOffsets`；偏移映射到章节绝对位置；空章节/纯空白处理。
- 预估行数：180
- 验证点：单测（偏移连续且覆盖全文、空章节、含标题段）；现有非混合路径不变（回归测试）。
- 依赖：步骤 10、16

**步骤 24. HybridSynthesisCoordinator**
- 文件：`app/.../service/readaloud/HybridSynthesisCoordinator.kt`
- 内容：窗口预取（2/2）、远程/兜底合成调度、`audioFor`、超时、暂停/取消、切换事件。
- 预估行数：200
- 验证点：协程单测（fake synth）：就绪用远程、未就绪用兜底、超时、恢复、取消；`runTest`。
- 依赖：步骤 13、16

**步骤 25. HttpReadAloudService 混合分支**
- 文件：`HttpReadAloudService.kt`
- 内容：`playCustomHybrid()`、进度更新、缓存键、段落间隔；非混合路径保持。
- 预估行数：200
- 验证点：`./gradlew testAppDebugUnitTest --tests "*HttpReadAloud*"` 全绿；人工冒烟（如有设备）。
- 依赖：步骤 24

**步骤 26. 兜底引擎分派与生命周期**
- 文件：`HttpReadAloudService.kt`、`HybridSynthesisCoordinator.kt`
- 内容：系统/HTTP/云合成器分派；失败链（无声）；暂停/恢复/翻章/停止；Toast 接入。
- 预估行数：180
- 验证点：单测（分派选择、失败降级）；人工冒烟。
- 依赖：步骤 25

#### 阶段 F：验收

**步骤 27. 全量测试与主验证集**
- 文件：无新增（修复缺陷除外）
- 内容：跑全部测试与门禁，修复发现的问题。
- 预估行数：≤200（修复）
- 验证点：
  - `./gradlew :modules:remote-link:testDebugUnitTest :modules:custom-tts:testDebugUnitTest` 全绿
  - `./gradlew testAppDebugUnitTest lintAppDebug verifyConfigArchitecture assembleAppDebug --continue --no-configuration-cache` 通过
  - `git diff --check` 无输出
- 依赖：步骤 7A、7B、22、26

**步骤 28. 交付说明与真机冒烟清单**
- 文件：`docs/dev/`（可选设计说明）或提交说明
- 内容：变更职责、设计取舍、验证结果、未验证风险；真机 UI 冒烟清单（配置/试听/首段兜底/断网切换/恢复）。
- 预估行数：60
- 验证点：人工核对清单覆盖 §4 功能验收全部条目。
- 依赖：步骤 27

### 3.2 编码规则

1. **强类型**（规则 9）：跨函数数据用 data class / enum；禁止裸 `Map<String, Any?>` 传递业务数据（JSON 边界与 msgpack 协议层除外）。
2. **模块边界**：`custom-tts` 禁止引用 Android API（`android.*`、`Context`、`SharedPreferences`）；`remote-link` 不承载朗读业务；app 负责组装。
3. **UI 约束**（legado AGENTS.md）：Compose + UDF/MVI；`@Stable` UiState；`ImmutableList`；ViewModel 经 Gateway 访问数据（不直连 DAO）；新代码放 `feature/customtts`。
4. **线程**：合成/网络在 IO 调度器；UI 状态更新在主线程；协调器生命周期与 service 绑定。
5. **错误处理**：任何合成/网络失败不得崩溃或静默丢失章节；按 §2.8 矩阵降级。
6. **测试**：JUnit4；纯逻辑测试不依赖 Robolectric；Robolectric 仅用于 ConfigStore/ViewModel；测试向量文件固定（跨语言一致性）。
7. **文本改动**：每个提交执行 `git diff --check`；提交信息按仓库现有 `feat/fix/test` 风格。
8. **零回归**：非定制引擎的朗读路径（系统/云/普通 HTTP）代码路径不得改变行为；相关回归测试必须通过。

## §4 验收标准

### 4.1 功能验收（对应需求文档 §3）

| # | 验收项 | 判定方式 |
|---|---|---|
| 1 | `remote-link` 远程连接功能有效 | 配置页"测试连接"成功；试听返回音频 |
| 2 | 异常/超时/断连稳定 | 非法 PSK、端口占用、断网、节点重启场景：App 不崩溃，配置页显示状态；恢复后重连成功 |
| 3 | 音色目录与参数经网关可用 | 配置页可拉到服务端音色列表；指定 voice/speed/instruct/seed/mode 后试听音频符合预期 |
| 4 | 定制引擎/音色可添加与配置 | 配置页保存后，「引擎与音色」页出现定制引擎与音色条目 |
| 5 | 参数能力覆盖 PC 前端 TTS | voice/speed/instruct/seed/mode + 分段阶梯 + 首段字数均可配置 |
| 6 | 试听功能 | 点击试听可听到选中音色（含参数）合成的音频；失败有提示 |
| 7 | 手机小屏布局 | 配置页在 360dp 宽度下无横向溢出、分组可滚动、BottomSheet 可操作（人工检查） |
| 8 | 逻辑收敛到独立 Gradle 模块 | `:modules:custom-tts` 存在且承载分段/参数/策略逻辑；`app` 仅做组装与 UI |
| 9 | 兜底引擎/音色可选 | 选择器列出系统/HTTP/云引擎（排除定制引擎），音色随引擎联动 |
| 10 | 服务不可用时无缝切换 | 断网/服务端停止时，当前段起自动用兜底，朗读不中断 |
| 11 | 首段兜底开关（默认开） | 新装默认开启；关闭后首段不强制兜底（远程未就绪时仍降级兜底） |
| 12 | 首段兜底策略 | 开启时首段（默认 20 字，可调）由兜底引擎朗读；远端请求并行进行 |
| 13 | 段级切换策略 | 每段播放前远程未就绪 → 该段用兜底；已就绪 → 用远程；不阻塞、不锁定 |
| 14 | 远端恢复自动切回 | 远程恢复返回后，后续段自动使用远程语音，无需手动操作 |
| 15 | 切换 Toast | 远程↔兜底切换时出现短暂 Toast（同方向 5s 防抖） |
| 16 | 双速度设置 | 兜底速度与定制速度可分别设置并生效 |
| 17 | 非 UI 逻辑自动化测试 | 见 4.4；全部测试通过 |

### 4.2 回归验收

1. `./gradlew testAppDebugUnitTest` 全绿（现有 281 个测试文件、约 1443 个用例）。
2. `./gradlew :modules:remote-link:testDebugUnitTest` 全绿（原有 7 个向量用例 + 新增用例）。
3. `./gradlew :modules:custom-tts:testDebugUnitTest` 全绿。
4. 系统 TTS / 云 TTS / 普通 HttpTTS 三种既有朗读路径行为不变（现有相关测试 + 人工冒烟）。
5. 缓存清理、预下载、段落间隔、定时关闭等既有设置行为不变。

### 4.3 架构验收

1. 模块依赖：`app → custom-tts`、`app → remote-link`；`custom-tts` 不依赖 Android API；两个模块互不依赖。
2. `./gradlew verifyConfigArchitecture` 通过（无新增 baseline 违规）。
3. 新 UI 代码位于 `feature/customtts`，未向旧 `ui/` 包新增同职责文件。
4. 无数据库 schema 变更（复用 `httpTTS` / `read_aloud_voices`）。
5. remote-link 的 wire protocol 字节不变（原有向量测试通过）。

### 4.4 测试验收（非 UI 逻辑）

| 范围 | 最低覆盖 |
|---|---|
| remote-link 协议层 | SessionCrypto 解密/重放/序列号；Noise 负向；Frame 边界；Fragmenter/Reassembler 边界；Msg 类型 |
| remote-link 状态机 | P2pClient 会话复用/重建/打洞失败落中继/乱序响应/超时/close |
| remote-link 网关 | 参数解析（7 参数含 timeout_ms、中文、边界值）、状态码映射、非音频响应、`/voices` 透传 |
| custom-tts 分段器 | 10 组跨语言一致性向量 + 边界（空文本/短句/长句/尾段） |
| custom-tts 策略 | 首段兜底、就绪/未就绪、超时、恢复、防抖、reset |
| custom-tts 参数 | 校验边界（speed 0.5/3.0、seed -1/0/99999、instruct 200 字、mode 枚举） |
| app 混合调度 | 窗口预取、远程/兜底选择、取消、暂停恢复、翻章重建 |
| app 配置 | 设置序列化、引擎/音色同步、ViewModel 状态流转（Robolectric） |

### 4.5 交付说明要求

最终说明必须包含：修改的职责范围、关键设计取舍（模块划分/分段复用/速度语义）、实际运行的验证命令与结果、未验证风险（真机 UI/外部服务/网络环境）、真机冒烟清单。

## §5 与现有需求文档的关系

| 文档 | 关系 |
|---|---|
| `2026-10-18-segmenter-v2.md` | 本需求 Kotlin 移植其分段规则（首段/阶梯/句末/尾并回），并以一致性向量绑定；不修改原 TS 实现 |
| `2026-10-19-tts-serial-pipeline.md` | 复用其"返回驱动 + 预取窗口"调度语义（INFLIGHT/LOOKAHEAD）；手机端段级赛跑是其混合引擎场景的扩展 |
| `2026-10-18-transport-watchdog.md` | 服务端在途看门狗（90s）与本需求客户端段级超时（10s）互补：客户端快速降级，服务端兜底清理 |
| `2026-10-18-relay-gateway-multiplex.md` | 中继多路复用为客户端（若后续放开并发）的前提；本需求不改协议 |
| 手机端仓库 `docs/dev/feature-first-structure.md` | 新 UI 按 Feature-first 规范落位（`feature/customtts`） |
| 手机端仓库 `AGENTS.md` | 构建命令、Compose 约束、设置边界、KMP 迁移纪律均适用 |

---

## 附录 A：需求原文要点映射

| 需求原文 | 本方案落点 |
|---|---|
| 2.1 remote-link 质量检查 | §2.2（8 项问题 + 8 类测试 + CI） |
| 2.2 定制引擎/音色 + 独立配置界面 + 试听 + 小屏 + 独立 Gradle 模块 | §2.3 / §2.4 / §2.5 |
| 2.3 兜底引擎/音色、无缝切换、首段兜底、Toast、开关、双速度、混合引擎 | §2.6 / §2.3.4 / §2.5.1 |
| 2.4 非 UI 逻辑自动化测试 | §3.1 步骤 5A/5B/6A/6B/11/12/13/24/27、§4.4 |
| §3 验收关注点 1-10 | §4.1 功能验收 1-17 |
