# agent多任务进化-新增searcher_agent

新增 searcher agent，实现到 @.opencode/agents 目录下。

**强制参考：**
1. @docs/进化/agent多任务进化/资料/prompts/searcher.tmpl
2. @docs/进化/agent多任务进化/资料/prompts/searcher-analysis.tmpl

**这两个文档来自于 PentAGI，是相对成熟的实现**，PentAGI 代码库路径：~/Documents/Codes/pentagi。

PentAGI 是面向渗透分析的 AI 系统，所以 searcher 里面的文案看起来就是偏向于渗透分析，有点像是 web-analysis agent 的功能，但是当前的 OpenSecurity 能力是全类型的 agents 你可以看 @.opencode/agents 下面的 agents，所以我希望在当前项目中创建的 searcher 能够满足所有类型的安全分析，但是创建多个 searcher 还是单个 searcher 我需要你详细调研、思考、分析。

我需要你分析 PentAGI 的 searcher 实现，分析 PentAGI 代码库的源代码，给我一个方案，我希望方案是完整的、成熟的！

这是从 PentAGI 进化的第一个agent，是一个标杆，满分100的话我要求你做到100。