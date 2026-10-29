# graphiti 适配器真链测试（消灭 FakeGraphiti 胶水盲区）

> 状态: 实施中
> 来源: 2026-09-27 晚全量验收复盘（4 个被掩盖生产 bug 中的 #2/#3 藏于本链）
> 关联: progress-2026-09-26-backend-oop-refactor.md「晚四」节

---

## §1 背景与目标

### 痛点（复盘数据）

2026-09-27 全量验收揪出 4 个被掩盖的生产 bug，其中两个藏身于 graphiti 组装链：

- `services/reranker.py` 裸调 `model_loader.rerank_sync`（实为类实例方法）→ diverse 搜索 500
- `services/graphiti_config.py` 裸调 `model_loader.embed_batch_sync`（同款）→ events 落库 500
- `Keys.DEEPSEEK_SMALL_MODEL` 在 config 合并时丢失 → `build_graphiti` 组装即炸

根因结构：test_control 的 3 个 events 编排用例注入 `FakeGraphiti`——一个 fake 把整条组装链
（`build_graphiti` + `BgeM3Embedder` + `BgeRerankerClient` + 配置键读取）整体短路。这层是
**纯项目胶水代码**（项目引用项目的适配层），fake 测试在原理上不可能发现其引用漂移。
其唯一动态覆盖是 test_e2e_real（依赖 Docker neo4j + DeepSeek + 生产控制台，单跑 ~2 分钟），
不在回归清单期间即全盲——上述 bug 正是在此窗口静默存活。

### 目标

为组装链三个组件新增**无 fake 的真实测试用例**（真 import + 真调用 + 真推理），
纳入 test_control 常规回归——每轮全量跑必覆盖。

### 四维度量

| 维度 | 现状 | 改后 |
|---|---|---|
| 结果准确度（遗漏率） | 适配器引用漂移仅 e2e_real 可抓（缺席即盲） | 单测层每轮必抓 |
| 分析速度（全量跑耗时） | — | +~2s（复用 E2E 段已加载模型） |
| 上下文占用 / 对话轮次 | — | 不变 |

## §2 技术方案

### 改动文件

| 文件 | 改动 |
|---|---|
| `tests/test_control.py` | 新增 1 个 @test 用例（置于 E2E /rerank 用例之后——两个 bge 模型已被真实加载，适配器推理零加载成本） |

生产代码零改动。

### 用例结构（四段断言）

```python
@test("graphiti 适配器真链: BgeM3Embedder/BgeRerankerClient/build 组装（无 fake）")
def test_graphiti_adapter_real_chain():
    # 1. BgeM3Embedder.create 单文本 → 1024 维（真推理）
    # 2. BgeM3Embedder.create_batch 双文本 → 2×1024（embed_batch_sync 引用——bug #3 藏点）
    # 3. BgeRerankerClient.rank(query, [相关段, 无关段]) → 长度 2 + 分数降序 + 相关>无关
    #    （rerank_sync 引用——bug #3 藏点）
    # 4. build_graphiti() → (graphiti, None)；断言 .embedder/.cross_encoder 实例类型
    #    是项目适配器（BgeM3Embedder/BgeRerankerClient）而非 graphiti 默认 OpenAI 实现
    #    （已实证: Graphiti.__init__ 未传参时静默默认 OpenAIEmbedder()——组装漏传
    #    不会报错只会走错模型，类型断言是唯一防线）;
    #    断言后 await graphiti.close() 释放 driver（neo4j 惰性连接，构造不连库）
```

异步方法（create/create_batch/rank）经 `asyncio.run()` 包装，与文件内既有用例模式一致。

### 环境前提

与 E2E 段一致：生产 `.ai_env` 的 DEEPSEEK_API_KEY（build 段需要）；bge-m3/bge-reranker 模型
缓存存在（E2E 段同样前提）。无 key 环境该用例报错合理（测试环境契约与 E2E 段统一）。

## §3 实现规范

### 改动范围表

| 文件 | 类型 | 行数 |
|---|---|---|
| tests/test_control.py | 新增用例（一个函数） | ~55 行 |
| requirements/evolve/progress-2026-09-26-backend-oop-refactor.md | 追加记录 | ~8 行 |

编码规则：遵循文件内既有 @test 模式（局部 import、assert_true/assert_eq、中文断言消息）。

### §3.1 实施步骤拆分

```
步骤 1. 新增用例前半段: BgeM3Embedder 真推理（create/create_batch）
  - 文件: tests/test_control.py
  - 预估行数: ~28 行
  - 验证点: 单点驱动（import tests.test_control + 直调用例函数）通过，
    且断言 create 返回 1024 维、create_batch 返回 2×1024
  - 依赖: 无

步骤 2. 扩展用例后半段: BgeRerankerClient.rank + build_graphiti 组装断言
  - 文件: tests/test_control.py
  - 预估行数: ~30 行
  - 验证点:
    a) 单点直调通过
    b) 防作弊验证: 临时将 graphiti_config.py 的 rerank 引用还原为旧 bug 形态
       （model_loader.rerank_sync 裸调用）→ 单点直调必红 → 还原 → 重跑绿
  - 依赖: 步骤 1

步骤 3. 全量回归 + 归档
  - 文件: progress 文档追加
  - 预估行数: ~8 行
  - 验证点: test_control 81/81（80→81）；耗时增量 <5s；
    e2e_real 6/6 不受影响；config_manager/api_guard 两族抽测绿
  - 依赖: 步骤 2
```

## §4 验收标准

### 功能验收

- 新用例四段断言全过（1024 维 / 2×1024 / rank 降序相关>无关 / 组装类型正确）
- 防作弊验证完成（注入旧 bug 形态必红）

### 回归验收

- test_control 81/81；全量耗时增量 <5s
  - **实施修订**: 实测增量 ~8s（77.8s vs 70s）——原预估"复用 E2E 段已加载模型"有误:
    E2E 段走共享控制台**子进程** HTTP，测试进程内模型仍需首次加载（bge-m3 ~5s +
    reranker ~2s）。真推理测试进程内必须持有模型，此成本不可免; ~8s 换组装链
    每轮覆盖，判定可接受（验收按实测增量 <10s 计）
- e2e_real 6/6；test_config_manager、test_api_guard 抽测绿
- 生产控制台不受影响（零生产代码改动，无需重启）

### 架构验收

- 生产代码零改动；测试用例遵循既有框架模式；无新文件散落

## §5 与现有需求文档的关系

- 吸收 `progress-2026-09-26-backend-oop-refactor.md`「晚四」的教训（回归盲区 → 本次把
  盲区层补上单测级动态覆盖）
- 与 [77] 结案档案（2026-09-27-test77-hang-investigation.md §9.3）同源：该轮抓到的
  submit 漂移是路由层胶水，本次补的是 graphiti 组装层胶水——同判据（fake 不许短路项目胶水）的延续
