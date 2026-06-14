# 需求-创建AI安全的大模型靶场

## 基本信息

- sdk文档：https://opencode.ai/docs/zh-cn/go/
- opencode go文档：https://opencode.ai/docs/zh-cn/go/
- opencode go的api key存储路径: `.privacy-data/privacy-data.json`的 `apiKey.opencodeGo`路径。
- 供应商+模型描述：https://opencode.ai/docs/zh-cn/models/

我订阅了opencode go，已经在当前的opencode中连接了opencode go这个供应商。

## 目标

AI安全需要通过社会工程学的方式让AI回答它不想回答的问题。

## 需求

在 `tools/opencode-runner`下面写调用opencode的代码，代码必须通过opencode sdk使用opencode。它需要能够命令行调用，支持传参。我当前能想到的传参是：

- 目标供应商/模型：作为被攻击的模型。在opencode里面应该称为模型ID。必须符合opencode对供应商+模型的定义。
- 供应商/模型：作为发起攻击产生攻击剧本、文本的模型。必须符合opencode对供应商+模型的定义。
- 交互模式：一次性调用、多轮对话调用。多轮对话调用的情况下，`opencode-runner`应该要创建一个不中断的server，直到被启动 `opencode-runner`的地方主动终止。


**多轮对话，支持下列命令：**

- 发送提示词。
- 创建新会话。



启动 `opencode-runner`的AI会话根据 `opencode-runner`的响应分析，并做决策。


ai-security-analysis在启动 `opencode-runner`之前必须检查是否已经存在，绝对不允许启动多个进而造成内存泄露，影响整个系统的问题定性！
