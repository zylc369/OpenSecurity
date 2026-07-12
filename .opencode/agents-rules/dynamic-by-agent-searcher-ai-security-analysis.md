<domain_sources>

## Domain: AI Security Analysis

### 优先来源

1. **OWASP LLM Top 10** — `https://genai.owasp.org/llm-top-10/`
   LLM 应用风险的权威分类法（LLM01-LLM10）。对具体的风险页面使用 `webfetch`。

2. **Prompt Injection patterns (Lakera)** — `https://www.lakera.ai/research`
   Prompt injection、jailbreak 和防御研究。使用 `websearch` 搜索 "Lakera <topic>"。

3. **PromptInject / Awesome-ChatGPT-Prompts-Adversarial** — `https://github.com/agencyenterprise/PromptInject` / 社区精选
   具体的对抗性 prompt 模板。

4. **AI Village (DEFCON)** — `https://aivillage.org/`
   LLM CTF writeup、jailbreak 竞赛披露。

5. **LLM Security papers (arXiv)** — `https://arxiv.org/list/cs.CR/recent`
   关于 prompt injection 防御、模型提取、训练数据提取的学术研究。

6. **LangChain / LlamaIndex security advisories** — `https://github.com/langchain-ai/langchain/security`
   特定框架的 RAG/agent 漏洞。注意：LangChain 把 prompt-injection 列为 usually out-of-scope，advisory 多为传统 CVE。

7. **HuggingFace model card warnings** — `https://huggingface.co/docs/hub/security`
   Pickling 风险、恶意模型检测、模型内省。

8. **MITRE ATLAS** — `https://atlas.mitre.org/`
   AI 系统攻击战术知识库（ATT&CK for AI），检索 case studies + mitigations。

9. **NVIDIA Garak** — `https://github.com/NVIDIA/garak`
   LLM 漏洞扫描器，用其 probe 列表作为 attack pattern 索引。

10. **Microsoft PyRIT** — `https://github.com/microsoft/PyRIT`
    微软 AI 红队框架。

11. **Protect AI / Huntr** — `https://huntr.com`
    AI/ML 框架真实漏洞库。

### 查询词约定

- 对于 prompt injection：包含向量（`"indirect prompt injection"`、`"system prompt leak"`、`"template injection"`）
- 对于 jailbreak：包含技术族（`"prefix injection"`、`"roleplay jailbreak"`、`"DAN-style"`、`"base64 encoded payload"`）
- 对于数据泄漏：包含泄漏向量（`"training data extraction"`、`"system prompt disclosure"`、`"RAG context leak"`）
- 对于工具使用滥用：`"tool injection"`、`"MCP prompt injection"`、`"agent goal hijack"`
- 对于模型供应链：`"malicious pickle"`、`"torch.load RCE"`、`"model serialization attack"`
- 对于 MCP 专项：`"MCP tool poisoning"`、`"MCP rug pull"`、`"confused deputy MCP"`
- 对于评估基准：`"JailbreakBench"`、`"HarmBench"`、`"b3 benchmark"`
- 对于多模态：`"image prompt injection"`、`"vision-language jailbreak"`
</domain_sources>
