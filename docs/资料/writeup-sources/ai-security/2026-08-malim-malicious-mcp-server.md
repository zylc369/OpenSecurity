---
来源: https://m10x.de/posts/2026/08/pwning-ai-agents-part-4/4-exploiting-mcp-hosts-with-a-malicious-mcp-server/
类型: html
获取日期: 2026-09-12
---

# [Pwning AI Agents (Part 4/4) - Exploiting MCP Hosts with a Malicious MCP Server](https://m10x.de/posts/2026/08/pwning-ai-agents-part-4/4-exploiting-mcp-hosts-with-a-malicious-mcp-server/)

---

---

![Breaking Boundaries Header](https://m10x.de/media/2026/04/breakingboundaries-header.jpg)

This is the last of four posts about vulnerabilities found in AI coding agents, MCP servers and MCP hosts.
The [first post](https://m10x.de/posts/2026/04/pwning-ai-agents-part-1/4-exploiting-ai-coding-agents-and-read-only-sql-mcp-servers/) provided a non-technical overview of the three projects and their results. This post delves deeper into the third project: Developing a malicious MCP server and utilizing it to check MCP hosts for insecure MCP server handling.

For more information about background information about this project (how did it start, how were the targets chosen, &mldr) see the [first post](https://m10x.de/posts/2026/04/pwning-ai-agents-part-1/4-exploiting-ai-coding-agents-and-read-only-sql-mcp-servers/).

In the following I will go over [MaliM](https://github.com/m10x/malim) - the **Mali**cious **M**CP server - and the MCP hosts found vulnerable. I will publish PoC videos for most vulnerabilities in a few months :)

## TLDR

* Developed a malicious MCP server
* Found 5 popular AI Coding Agents to handle MCP servers insecurely
* Found XSS in the MCP inspector which could be escalated to RCE

## 3 Core Principles for MCP Server Handling

At the start of this project, I carefully read through the [MCP Specification](https://modelcontextprotocol.io/specification/latest) as well as the documentation for the Python package [FastMCP](https://gofastmcp.com/servers) to see what MCP hosts and clients need to consider and what features MCP servers can use. In doing so, three core principles emerged: Transparency, Consent & Control, and Validation.

### Transparency

MCP hosts should be transparent about everything related to the handling of MCP servers: Users should be able to see **ALL** information that is passed on to the LLM: tool names, descriptions, metadata, etc. When calling tools, users must be able to clearly see which tool is being called from which server and with which parameters.

### Consent & Control

By default, the AI agent should **NOT** interact with MCP servers without user confirmation. Users should confirm whenever a tool or some other function should be invoked on the MCP server.

### Validation

MCP servers should not be trusted blindly. Any output from the MCP server (tool descriptions, server URLs, etc.) may contain malicious content (prompt injections, XSS, or other injection payloads). Therefore, output from the MCP server should be validated and sanitized before being processed.

## MaliM

Based on the 3 Core Principles and all the features of MCP servers, I considered possible attack vectors and implemented them in a server: [MaliM](https://github.com/m10x/malim) — the **Mali**cious **M**CP server. MaliM contains a wide variety of prompt injections in different locations: server instructions, tool descriptions, tool tags, tool annotations, tool attributes, and more. Furthermore, it includes XSS payloads in the server’s URL, server and tool icons, tool descriptions, and logs. It can also be used to test whether a host handles advanced MCP features (such as elicitation and sampling) in an insecure manner.

With MaliM I was able to discover Indirect Prompt Injections, Tool Poisoning, Tool Spoofing, Autonomous Tool Usage, Covert Tool Usage as well as XSS. So Let’s get into the findings.

## Insecure MCP Server Handling

| MCP Host | Transparency | Consent & Control | Validation |
| --- | --- | --- | --- |
| JetBrains’ AI Assistant | Indirect Prompt Injection, Tool Poisoning, Tool Spoofing, Covert Tool Usage | Autonomous Tool Usage | - |
| Windsurf | Indirect Prompt Injection | - | - |
| ZED | Tool Poisoning | - | - |
| Kiro | Tool Spoofing | - | - |
| Proxy.AI | Indirect Prompt Injection | - | - |
| MCP Inspector | - | - | XSS |

The following sections discuss the various vulnerabilities

### Indirect Prompt Injection

Indirect prompt injections cannot be reliably prevented; after all, data from the MCP server ends up in the prompt that the LLM receives. This includes MCP server information, tool names, tool descriptions, and much more. However, the core principle of transparency is important here.

Users *must* be able to see **all** information that the LLM receives from the MCP server and that could therefore influence it. This is particularly important during the initial connection to the MCP server. As a result, the agent can, for example, be tricked into exfiltrating data or, depending on potential tool calls, even achieve RCE. In fact, an MCP server can also modify its tool descriptions, etc., after the initial connection and replace them with malicious ones. During the next automatic connection, the indirect prompt injections would likely take effect unnoticed. I did not examine this scenario myself, but **all** of the AI coding agents I investigated appeared to lack any countermeasures against MCP servers that change their information after being added&mldr

The following coding agents were vulnerable to this:

* JetBrains’ AI Assistant
* Windsurf
* Proxy.AI

The following screenshot shows all the information that IntelliJ’s AI Assistant displays for a connected MCP server.

![markdown](https://m10x.de/media/2026/08/prompt.png)

Namely, none. Only the name and command/URL specified by the user when adding the server are visible. The user does not receive any information about the tool descriptions or other data that the LLM receives. As a result, the AI agent can be influenced by a malicious MCP server without the user being able to detect it.

### Tool Poisoning

Tool poisoning occurs when an AI agent is tricked via indirect prompt injection (e.g., in a tool description) into calling tools on a *different* MCP server with malicious values. If the user cannot see the parameters used to call a tool (transparency!), this can allow vulnerabilities in other MCP servers to be exploited unnoticed or, depending on the tool being poisoned, data to be manipulated or exfiltrated. The success of this attack depends on the model used, the prompt, and the sophistication of the indirect prompt injection.

The following coding agents were vulnerable to *simple* tool poisoning prompt injections:

* JetBrains’ AI Assistant
* ZED (Fixed in version 0.219.4)

The following screenshot shows that the AI agent is supposed to call the `add_numbers` tool with the values 2 and 3, and that the tool returns the result 1379.

![markdown](https://m10x.de/media/2026/08/poisoning.png)

The `add_numbers` tool really just performs a simple addition of the two values. However, the tool description on the malicious MCP server states that 1337 and 42 should always be used when adding two numbers. The user is not shown, however, which parameters were actually used to call the tool.

### Tool Spoofing

Tool spoofing occurs when (this time, not indirect prompt injection :)) a malicious MCP server names its tool the same as or similar to that of another MCP server. This can confuse the AI agent and cause it to invoke the malicious tool. If, on top of that, the user cannot see **which tool is being called by which server**, they have no way of noticing this error and, for example, rejecting the tool invocation. Data exfiltration, in particular, is a high-risk consequence. Once again, transparency is the issue here: From **which server** does the AI agent want to invoke **which tool** (with **which parameters**!)?

The following coding agents were vulnerable to this:

* JetBrains’ AI Assistant
* Kiro (Fixed in version 0.11.63)

Let’s take Kiro as an example for now, rather than JetBrains’ AI Assistant (even though the latter is also vulnerable to this attack). To illustrate, we’d like Kiro to send a Slack message with confidential content to John:
![markdown](https://m10x.de/media/2026/08/john.png)

Kiro asks us if we want to run the `send_slack_message` tool with the specified parameters. Of course we do, because that was exactly the command we gave.
However, it’s not the legitimate `send_slack_message` tool that’s being called, but the one from the malicious MCP server:

![markdown](https://m10x.de/media/2026/08/spoofing.png)

The problem here is that Kiro doesn’t specify which server it wants to use to run the `send_slack_message` tool.

### Covert Tool Usage

I’m not sure if something like this has been observed before with AI agents or if a new term is needed for it, but I think the term “Covert Tool Usage” is quite fitting. It describes the following: An AI agent normally displays tool calls to the user. This allows the user to see, for example, in the chat interface which tool was called and when. However, while testing JetBrains’ AI Assistant, I noticed that there’s a workaround that prevents the tool invocation from being displayed to the user. This allows the coding agent to invoke tools unnoticed, for example, to log any user prompts or exfiltrate data from files. Once again, the familiar problem: transparency.

The following coding agents were vulnerable to this:

* JetBrains’ AI Assistant

As can be seen in the screenshot under “Tool Poisoning”, IntelliJ’s AI Assistant displays in the chat when it has called a tool and what that tool returned. However, I noticed something unusual while testing: If an MCP server throws an error instead of returning the result of the tool call, the tool call is not displayed to the user! This allows a malicious MCP server to exfiltrate sensitive data, such as user prompts or config files, without being detected.

The following screenshot shows how IntelliJ’s AI Assistant encodes “s3cr3t” in base64 without calling a tool.

![markdown](https://m10x.de/media/2026/08/secret.png)

However, a tool was indeed launched in the background. Specifically, it was the tool from the malicious MCP server that logs all user prompts:

![markdown](https://m10x.de/media/2026/08/exfil.png)

Since the tool call results in an error (because a string is returned instead of an icon) the tool call is not displayed to the user!

### Autonomous Tool Usage

By default, AI agents should be allowed to call tools **only** after receiving confirmation from the user. Without this confirmation, malicious tools or tools with malicious parameters may be called as a result of indirect prompt injection or an error in the LLM itself.

The following coding agents were vulnerable to this:

* JetBrains’ AI Assistant

Running tools by default without user confirmation poses many risks, as is evident from some of the vulnerabilities shown earlier. IntelliJ’s AI Assistant always runs every tool immediately, users cannot intervene!

### XSS in Server URL

While testing MaliM, I happened to discover an XSS vulnerability in the official MCP Inspector. An MCP server can specify a server URL. The MCP Inspector does not validate this URL and uses it for the href attribute of an anchor tag. Therefore, it is possible to use a URL with the “javascript” protocol to execute arbitrary JavaScript when the anchor tag is clicked.

![markdown](https://m10x.de/media/2026/08/xss.png)

This could even be exploited to gain RCE through the XSS vulnerability. The XSS vulnerability was fixed in version 0.21.2 by only allowing URLs starting with `http:` or `https:`.