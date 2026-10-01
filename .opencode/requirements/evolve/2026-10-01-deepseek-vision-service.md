# DeepSeek 视觉识别服务（无视觉能力模型的"眼睛"）

- 日期: 2026-10-01
- 状态: **已实施、已验证、生产已生效**（控制台 15:40 重启加载; MCP 注册待 opencode 重启）——详见 .progress.md
- 来源: 用户直接需求——"有些模型（如 GLM-5.3）没有视觉能力，靠 OCR 还是不行"

## §1 背景与目标

### 1.1 痛点

无原生视觉能力的模型（如 GLM-5.3）目前只能靠 `ocr_extract_text`（本地 glm-ocr，纯文字转写）
获取图像信息。OCR 回答不了语义级问题："这个柱状图里哪根最高""这两个报错对话框有什么区别"
"这个 UI 布局有几个输入框"。**语义级看图能力缺失 = 0→1 缺口**。

### 1.2 Phase 1 决策记录（用户已裁定）

| 决策点 | 裁定 |
|---|---|
| 多图 | **支持 1-4 张**（对比/关联分析） |
| 模型 | **写死 `deepseek-flash`**，零新增配置键——"以后要新增模型大概率要改代码，默认无必要"（max_tokens/timeout 一并代码常量化） |
| 命名 | MCP server `vision` / 工具 `analyze_image` / 路由 `POST /api/vision/analyze` |
| 工具描述门槛 | vision 描述必须写明"**仅限无原生视觉能力的模型使用**；有原生视觉的模型直接用 Read 读图，调用本工具反而绕远路" |
| OCR 描述 | 小改互补指引（**不加**"仅限无视觉模型"——OCR 对有视觉模型同样有价值: 精确转写/防感知幻觉交叉验证）; "不支持图表语义分析/对比"处指向 `analyze_image` |

### 1.3 实测依据（Phase 0）

- `deepseek-flash` 经 OpenAI 兼容端点 `POST https://api.deepseek.com/chat/completions`
  + `image_url`(data URL) 内容块**实测有视觉能力**（正确识别测试图"红底黑字 A"，72 completion tokens）。
- `deepseek-v4-pro` 接受图像但为推理型（100 max_tokens 全烧 reasoning，content 空）——不采用。
- 官方 `/models` 仅此两模型，无独立 VL 模型名。

## §2 技术方案

### 2.1 架构位置

```
agent（无视觉模型）
  └─ MCP vision/analyze_image（薄壳: 读文件→b64→POST IPC）
       └─ 控制台 POST /api/vision/analyze（严格 pydantic 契约 → 422）
            └─ services/vision_service.py（魔数校验已在上层完成; 构造多模态 payload）
                 └─ https://api.deepseek.com/chat/completions（deepseek-flash）
```

与 `ocr`（本地 glm-ocr）**互补不重叠**：OCR=逐字符转写（全模型可用）;
vision=语义理解（仅无视觉模型）。

### 2.2 新增文件与改动

| 文件 | 动作 | 内容 |
|---|---|---|
| `control/backend/services/vision_service.py` | 新增 | 见 §2.3 |
| `control/backend/routes/vision.py` | 新增 | 见 §2.4 |
| `control/backend/server.py` | +2 行 | import + include_router（`app.include_router(ocr.router)` 同段） |
| `mcp-servers/vision/server.py` | 新增 | 薄壳（镜像 `mcp-servers/ocr/server.py` 模式） |
| `plugins/lib/mcp-manager.ts` | +6 行 | `MCP_SERVERS[]` 增加 vision 条目（timeout 60000，同 ocr） |
| `mcp-servers/ocr/server.py` | ~2 行 | 描述补互补指引 |
| `control/backend/tests/test_control.py` | 追加 | 契约 422 矩阵 + 服务级 mock 上游（见 §4） |
| `control/backend/tests/test_e2e_real.py` | 追加 | 真链路 live 用例（门控: 显式运行才执行） |

**零改动**: config_manager.py（无新键，复用 `DEEPSEEK_API_KEY`）、所有 agent prompt（工具自描述）。

### 2.3 vision_service.py（服务层，框架无关）

```python
# 常量（写死——Phase 1 决策: 不进配置）
MODEL = "deepseek-flash"
API_URL = "https://api.deepseek.com/chat/completions"
MAX_TOKENS = 2048
TIMEOUT_SEC = 120.0
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 解码后单张上限
MAX_QUESTION_CHARS = 8000

@dataclass(frozen=True)
class VisionImage:      # data: bytes; media_type: str（image/png|jpeg|gif|webp|bmp）
@dataclass(frozen=True)
class VisionAnalyzeResult:  # text: str; model: str; prompt_tokens/completion_tokens/total_tokens: int; latency_ms: int

class VisionUpstreamError(Exception):
    # message: str; status_code: int（503 key缺失 / 502 上游错误·结构异常·空内容 / 504 超时）

class VisionService:    # 静态方法类（无状态，同 GraphitiFactory 风格）
    @staticmethod sniff_media_type(data: bytes) -> str | None
        # PNG \x89PNG\r\n\x1a\n | JPEG \xff\xd8\xff | GIF87a/GIF89a | RIFF....WEBP | BM
    @staticmethod async analyze(images: list[VisionImage], question: str, *,
                                transport: httpx.AsyncBaseTransport | None = None  # 测试注入
                                ) -> VisionAnalyzeResult
```

`analyze` 逻辑: key 检查(缺→503) → 构造 content（text 块 + 每图一个 image_url data URL 块）
→ `async with httpx.AsyncClient(timeout=TIMEOUT_SEC, transport=transport)` POST →
非 200 → 502（含上游状态码+body 前 300 字符）; 解析 `choices[0].message.content` /
`usage`（结构异常→502）; content 空白 → 502（"空内容: reasoning 耗尽 max_tokens 或被过滤"）;
返回结构化结果。全程 logger 记录（图片数/问题长度/模型/tokens/latency/错误）。

### 2.4 routes/vision.py（契约层）

```python
def _reject_blank(v: str) -> str          # 与 events.py 同语义（第 2 处出现，暂不复用抽象）

DecodedImage = Annotated[VisionImage, BeforeValidator(_decode_image)]  # b64→解码+校验+定型
# _decode_image: b64decode(validate=True) 失败→"非法 base64"; 空数据→"图片数据为空";
#                >MAX_IMAGE_BYTES→"图片过大"; 嗅探失败→"不支持的图片格式(PNG/JPEG/GIF/WEBP/BMP)"

class AnalyzeIn(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)   # VisionImage 为任意类型
    images: list[DecodedImage] = Field(min_length=1, max_length=MAX_IMAGES)
    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION_CHARS),
                         AfterValidator(_reject_blank)]

@router.post("/analyze")
async def analyze(req: AnalyzeIn) -> VisionAnalyzeResult:
    # VisionUpstreamError → HTTPException(exc.status_code, str(exc))
```

**契约矩阵（全部显式 422，与 events 契约同风格 detail 列表）**: 缺 images / 空列表 / >4 张 /
坏 b64 / b64 解码后非图片字节 / 解码后空 / 单张 >10MB / 缺 question / 空白 question /
question >8000 字符。

### 2.5 MCP 薄壳（mcp-servers/vision/server.py）

镜像 ocr 薄壳: `_lifespan` 建 `make_control_client(timeout=300.0)`、`_base_url()` 延迟解析 +
失败自愈（404/502/HTTPError 清缓存）。工具:

```python
@mcp.tool(description=(
    "视觉理解（DeepSeek 视觉模型，语义级问答）。"
    "【仅限无原生视觉能力的模型使用】——有原生视觉识别的模型应直接用 Read 工具读图，"
    "调用本工具反而把路走远了。"
    "适合：图表语义分析、UI 布局理解、截图对比/差异分析、验证码/图形内容理解、场景描述。"
    "支持 1-4 张图（多图=对比/关联分析）。"
    "仅需逐字符精确转写文字（代码/十六进制/表格）→ 用 ocr_extract_text（更精确）。"
    "不支持：视频理解、音频。"))
async def analyze_image(image_paths: Annotated[list[NonBlankStr], Field(min_length=1, max_length=4, ...)],
                        question: Annotated[NonBlankStr, ...]) -> str
```

薄壳侧检查: expanduser + is_file + 原始字节 >10MB 快速失败（与控制台同限，失败早报）;
成功返回 `json.dumps(VisionAnalyzeResult, ensure_ascii=False)`; 失败返回
`"[错误] 控制台视觉识别返回 {status}: {text[:200]}"`（镜像 ocr 文案）。

### 2.6 OCR 描述调整（mcp-servers/ocr/server.py）

"不支持：图表语义分析、图像内容对比、视频理解。" →
"不支持：图表语义分析、图像内容对比、视频理解——前两类语义需求（无视觉能力模型）用 vision 的 analyze_image。"

## §3 实现规范

- 编码: 强类型（规则 9）——dataclass 定型、无裸 dict 业务传递（DeepSeek payload 为 HTTP 序列化边界，合法例外）;
  服务层框架无关（不 import fastapi，异常自定义）; 薄壳不依赖控制台代码（只经 control_url）。
- 日志: 服务层关键路径全打（规则 10 精神）; MCP 薄壳 stdout 为协议流禁写，错误走返回值。

### §3.1 实施步骤

1. **services/vision_service.py**（新增 ~150 行）
   - 验证点: `compile` + pyright backend 0/0/0; python -c 冒烟断言嗅探（PNG/JPEG/GIF/WEBP/BMP/垃圾字节六例）
2. **routes/vision.py + server.py 挂载**（新增 ~80 行 + 2 行）
   - 验证点: compile + pyright; TestClient 探针（空 images→422、坏 b64→422）
3. **mcp-servers/vision/server.py 薄壳**（新增 ~110 行）
   - 验证点: compile + pyright mcp-servers 0/0/0; import 冒烟（FastMCP 实例化不启动）
4. **mcp-manager.ts 注册 + ocr 描述调整**（+6 行 / ~2 行）
   - 验证点: `bun build mcp-manager.ts --target=bun --outfile=/dev/null` 编译冒烟;
     grep 断言 MCP_SERVERS 含 vision; ocr 描述含 analyze_image 指引
5. **test_control.py 路由契约矩阵**（追加 ~130 行: 422 十例 + 沙箱 503 例）
   - 验证点: `python tests/test_control.py` 全绿（旧 95 + 新增全过）
6. **test_control.py 服务级 mock 上游**（追加 ~110 行: 正常解析/401/429/超时/结构异常/空内容 + transport 注入）
   - 验证点: 同上全量复跑
7. **test_e2e_real.py 真链路用例 + live 验证**（真图内存生成 b64 直调; 薄壳直调用临时文件写 /tmp 并清理）
   - 验证点: e2e 用例过（真 key 真模型）; 控制台自重启后 curl 探针（422 矩阵抽样 + 真 200 答案）;
     薄壳 import 直调（OPENSECURITY_CONTROL_IPC 注入）走通 IPC→控制台→DeepSeek
8. **收尾**: progress.md 全程记录; pyright 全量复跑; 文档字节扫描; 交付报告（含 opencode 重启提醒——MCP 注册生效条件）

依赖顺序: 1→2→(3,4 可并行)→5→6→7→8。单步均 ≤200 行。

## §4 验收标准

**功能验收**:
- [x] §2.4 契约矩阵 10 类全部显式 422（detail 结构与 events 一致）
- [x] key 缺失（沙箱无 .ai_env）→ 503 且文案含"DEEPSEEK_API_KEY 未配置"
- [x] mock 上游: 正常响应解析为结构化 VisionAnalyzeResult（含 usage/latency_ms）;
      401/429/超时/结构异常/空内容 → 对应 502/504 错误
- [x] 真链路: 测试图（红底黑字 A）→ 答案含"红"或"A"语义
- [x] MCP 薄壳: 文件不存在/超尺寸 → 明确错误文案; 真调用返回 JSON 文本
- [x] vision 工具描述含"仅限无原生视觉能力"; ocr 描述含互补指引

**回归验收**:
- [x] `python tests/test_control.py` 全绿（存量 95 例无回归）
- [x] pyright backend / mcp-servers 均 0/0/0
- [x] 存量 MCP（knowledge/events/ocr/proxy）注册路径未动——仅追加数组条目

**架构验收**:
- [x] 服务层不 import fastapi; 薄壳仅经 control_url（不依赖控制台代码）
- [x] config_manager.py 零改动（无新键）
- [x] agent prompt 零改动 → Phase 4.5 跳过成立（无 prompt 行数变化）

## §5 与现有需求文档的关系

- `2026-10-01-events-input-contract-tightening.md`: 本战役复用其契约风格（NonBlankStr/
  显式 422/测试矩阵模式），无代码交集（events.py 不动）。
- `2026-08-20-ipc-no-port-files.md`: 薄壳经 control_url IPC，符合既有约定，无冲突。
