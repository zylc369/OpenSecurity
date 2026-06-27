# 进度摘要：环境变量重命名

## 任务
$SCRIPTS_DIR/$IDA_SCRIPTS_DIR → $AGENT_DIR/$SHARED_DIR

## 完成状态：全部完成

| 步骤 | 状态 | 改动要点 |
|------|------|---------|
| 1. Plugin 重命名 | ✅ | 4 处注入文本：变量名 + 中文描述 |
| 2. binary-analysis prompt | ✅ | 16 处 $SCRIPTS_DIR → $AGENT_DIR + 1 处 $IDA_SCRIPTS_DIR → $SHARED_DIR + 中文描述 |
| 3. mobile-analysis prompt | ✅ | 16 处变量重命名 + 中文描述 |
| 4. security-analysis-evolve prompt | ✅ | 1 处 $IDA_SCRIPTS_DIR → $SHARED_DIR |
| 5. binary-analysis 知识库（8 文件） | ✅ | ~50 处 $SCRIPTS_DIR → $AGENT_DIR |
| 6. mobile-analysis 知识库+脚本（8 文件） | ✅ | ~19 处重命名 |
| 7. binary-analysis registry.json | ✅ | 8 处 $SCRIPTS_DIR → $AGENT_DIR |
| 8. commands 文档（3 文件） | ✅ | ~6 处重命名 + 中文描述 |
| 9. 全局验证 | ✅ | grep/node --check/JSON 验证全部通过 |

## 验证结果
- Plugin `node --check` ✅
- registry.json x2 `json.load()` ✅
- 全局 grep 确认无遗漏（活跃文件中旧变量名零残留） ✅
- 历史需求文档中旧变量名保留（设计记录，不改） ✅
- manage_frida.py 中 FRIDA_SCRIPTS_DIR 保留（Python 内部变量，不改） ✅
