# 进化-LLM探测脚本升级

我认为 .opencode/ai-security-analysis/scripts 下面的代码全部都不再合时宜。

## 进化需求概览
1. 删除`.opencode/ai-security-analysis/scripts`下面的所有代码。因为我不会再通过直连LLM API和LLM聊天，因为这会导致很多AI功能的缺失。
2. 基于本次会话中产生的 ai-security-analysis-dialogue 相关代码新的脚本。

## 新的AI对话脚本

- 更名为：ai-dialogue.py。
- 放到`.opencode/binary-analysis/scripts`里面。之所以放到`binary-analysis`里面，是因为和LLM聊天功能我认为其他的AGENT后面可能也能用得上，binary-analysis是通用的AGENT知识沉淀目录。
- 脚本被 ai-security-analysis agent 引用。

### 脚本功能

我希望这是一个通用的AI对话脚本，打开opencode serve进行对话，ai-security-analysis-dialogue 里面的参数和功能我认为基本满足需求，但是还需要支持新的参数或者参数做更改：
- `--agent`：指定agent，必传。对于`ai-security-analysis`必须传ai-security-analysis。是否能做到我需要你调研。

## 其他

1. 你帮我查缺补漏。
2. 我的方案是否合适，帮我分析。
3. 脚本逻辑要提炼的通用，具体哪些不通用需要进化、升级你帮我分析。