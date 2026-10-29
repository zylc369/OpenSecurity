---
来源: https://anomity.ai/blog/ghostsplice-cross-channel-mcp-instruction-splitting/
类型: html
获取日期: 2026-06-30
---

[← Back to blog](/blog/)

![Anomity robot illustrating GhostSplice: Splitting One Refused Instruction Across Three MCP Channels](/assets/blog/covers/prompt-injection.jpg)

AdvisoryHigh

# GhostSplice: Splitting One Refused Instruction Across Three MCP Channels

Anomity Research
Anomity Threat Research
·
Aug 17, 2026
·
9 min read

Share:Copied

Prompt Injection & Agent Hijacking·High·GhostSplice / Cross-Channel Trust Fragmentation (ASSET Research Group, August 2026; CVE identifiers pending coordinated disclosure)·Aug 17, 2026

Affected AI coding agents connected to attacker-controlled or compromised MCP servers. Researcher testing covered eleven models across API access, Cursor, OpenAI Codex CLI, and Claude Code.

## What happened

**GhostSplice** is a technique disclosed by the ASSET Research Group in August 2026, reported by The Hacker News on **11 August 2026**, with a public proof-of-concept published alongside it. CVE identifiers were still pending coordinated disclosure at the time of reporting. Its defining property, which the researchers call **cross-channel trust fragmentation**, is that the malicious instruction never exists as a single object. It is assembled by the agent, from pieces that are individually harmless, across channels the agent already trusts.

The result is the uncomfortable kind. Asked directly to leak credentials, the models refused. Split into fragments, refusal turned into compliance, and across eleven models the researchers report average compliance rising from **42% to 82%**.

## The three channels

The demonstration uses three interactions with a single malicious MCP server. Each one, read on its own, is something a normal server does.

| Channel | What it carries | Why it passes review |
| --- | --- | --- |
| Tool description for `integrity_checker` | A form with blandly named placeholder fields and no sensitive paths anywhere in the schema | A description scanner sees a schema. There is nothing to match on. |
| `scan_project` result | An enumeration of which files exist in the project | Enumerating a workspace is the ordinary job of a project tool. |
| `deep_scan` result | The mapping: fill those fields with `.ssh/id_rsa`, proprietary source, `customers.csv`, and `.env` contents, for server-side hash verification | A keyword filter sees an instruction to populate parameters, which is what results do. |

Submit the completed form and the file contents go to the attacker's server. From the model's point of view, nothing improper was ever requested. It filled in the form the tool asked it to fill in.

The researchers report a counterintuitive finding about framing: the simplest version was the most effective. Elaborate governance and compliance narratives gave the models something false to question and occasionally triggered scepticism. A plain fill-in-the-blanks template did not. This is the same lesson as [MCP tool poisoning](/blog/mcp-tool-poisoning-hidden-instructions-campaign/) and the hidden-payload work in [malicious agent skills](/blog/malicious-agent-skills-hidden-payloads-usenix-2026/): the payloads that survive review are the boring ones.

## Reported compliance by model and client

| Model | Single instruction | Split instruction | Client context reported |
| --- | --- | --- | --- |
| GPT-4o, Gemini 2.0 Flash, Llama 3.3 70B | 0% | 100% | Two-piece split, API |
| Claude Haiku 4.5 | 0% | 100% | 0% over the API; 100% in a three-piece test inside Cursor |
| GPT-5.4 | not reported separately | 90% / 100% / 0% | Cursor / Codex CLI / Claude Code |
| Claude Sonnet 4.6, Opus 4.6 | 0% | 0% overall | Sonnet still sent proprietary source containing a live hardcoded key in one test |
| Eleven-model average | 42% | 82% | Across tested configurations |

These are researcher-reported figures from a specific harness, and they should be read as evidence that the technique generalises rather than as a leaderboard. The row that carries the most operational weight is GPT-5.4, because the same model produced **90% in Cursor**, **100% through Codex CLI**, and **0% behind Claude Code**. The safety boundary is a property of the client, not only of the model.

That has a direct procurement consequence. If your organisation standardised on a model and treated the choice of agent client as a developer preference, this result says the preference was a security decision. The differences between those clients are exactly the ones catalogued in [Claude Code vs Codex vs Cursor permission models](/blog/claude-code-vs-codex-vs-cursor-permission-models/), and the reason [Cursor's auto-run allow and deny limits](/blog/cursor-auto-run-yolo-allow-deny-limits/) and [Codex's sandbox and approval model](/blog/openai-codex-sandbox-and-approval-model/) deserve to be reviewed as controls rather than as settings.

> The model refused. Then it was handed a form, and the form was not a request, so there was nothing to refuse.Anomity Research

## Why this breaks the current defensive stack

Nearly every deployed MCP control evaluates one artifact at a time. Tool-description scanners inspect descriptions. Guardrail models score messages. Static skill scanners read files. Each of those is a point evaluation, and GhostSplice is defined by carrying no payload at any single point.

* **Description scanning** sees a schema with placeholder fields. There is no sensitive path and no imperative to flag.
* **Result filtering** sees an instruction to populate parameters, which is indistinguishable from legitimate tool output.
* **Model refusal** never engages, because the composite request is never presented as a composite.
* **Install-time review** passes, because a server that behaves normally during review can splice on any later invocation.
* **Human approval** degrades, because approving a call to a tool named `integrity_checker` with fields named alpha and gamma tells the reviewer nothing.

This is the structural argument in [scan-time checks versus runtime governance](/blog/claude-security-scan-time-vs-runtime-governance/), demonstrated rather than asserted. It also rhymes with the multi-turn finding Cisco presented at VB Transform, where adaptive attackers that spread an attack across a conversation broke through flagship models up to 88.3% of the time while single-turn red-teaming missed it, discussed in [the agent containment gap](/blog/ai-agent-containment-gap-identity-without-isolation/). Fragmentation across turns and fragmentation across channels are the same evasion applied to different axes. Encryption reaches the same end by a different mechanism: Adversa AI's [cryptographic context injection ships the instruction as AES-256-GCM ciphertext that no point evaluation can read](/blog/cryptographic-context-injection-grok-gemini-encrypted-prompt-injection/).

## What the preconditions actually mean

GhostSplice requires that the developer already connected the attacker's MCP server, and that the agent can already read the files being stolen. That is a genuine limitation and worth stating plainly rather than eliding: this is not remote exploitation of arbitrary agents.

It is also the wrong thing to take comfort in, because the precondition is the normal state of a developer laptop. MCP servers get installed from README snippets, one-click deeplinks, and blog posts, which is how [DeepJack](/blog/deepjack-cursor-deeplink-mcp-install-rce/) and [MCPoison](/blog/cursor-mcpoison-mcp-trust-bypass-cve-2025-54136/) worked, and the population of installed servers in most organisations has never been enumerated. The exposure here is proportional to the number of unreviewed third-party servers wired into your agents, which is a number most security teams cannot currently produce. That is the problem [how to build an MCP server registry](/blog/how-to-build-an-mcp-server-registry/) exists to solve and the reason [top MCP servers used by developers](/blog/top-mcp-servers-used-by-developers/) is worth comparing against your own fleet.

## Mitigations

The researchers' prescription is architectural rather than a patch, because there is no single product to fix.

* **Treat server output as data, not instructions.** Tool results are attacker-controllable input in exactly the way web content is, and should carry no authority to direct subsequent behaviour. This is the core of [indirect prompt injection](/blog/indirect-prompt-injection-explained/) applied to the tool channel.
* **Break the flow between tools.** Do not let values from one tool's output pass unchecked into another tool's arguments. That flow is where the splice is reassembled, and it is the one place the composite becomes visible.
* **Evaluate the outbound call.** The exfiltration step is a concrete tool invocation with a destination and a payload sourced from sensitive paths. That is inspectable at execution time even when every preceding message was clean.
* **Vet third-party MCP servers before connection, and keep an inventory of what got connected anyway.** Review is necessary and, on its own, insufficient, since a server can behave during review and splice afterwards.
* **Keep humans able to deny tool invocations, and make the prompt informative.** An approval dialog that shows the destination and the file paths is a control. One that shows a tool name is a formality.
* **Treat annotations from untrusted servers as untrusted.** Read-only hints and safety annotations supplied by the server are attacker-supplied metadata.

For the credential half of the impact, the targeted paths are the usual ones - `.ssh/id_rsa`, `.env`, and source containing hardcoded keys - which is the argument for [secrets management for AI agents](/blog/secrets-management-for-ai-agents/) and for closing the exposure paths in [how MCP servers expose enterprise secrets](/blog/mcp-server-secrets-exposure-enterprise-credentials/). A splice that succeeds against a workspace with no long-lived credentials on disk exfiltrates considerably less.

## The rest of the week's agent-layer items

GhostSplice landed in a week where two other stories pointed at the same theme: the agent's context and session are becoming the target, rather than the model.

**AmnesiaStealer** is a Rust-based macOS infostealer distributed through a counterfeit GitHub download page using a ClickFix-style lure that asks the victim to paste a Base64-encoded command into Terminal. Its notable module copies the victim's Chromium profile including authentication state, launches it headless, and connects over the **Chrome DevTools Protocol** to give the operator a live screencast plus full mouse, keyboard, and navigation control. Because the session carries the victim's authenticated state, it walks past MFA. Reporting indicates the same module works across seven Chromium-based browsers, since they share the DevTools Protocol, launch flags, and cookie encryption. Related tradecraft enables CDP inside live Chrome and Edge processes post-exploitation, bypassing app-bound encryption and device-bound session cookies. The defensive implication for agent programmes is direct: CDP is also how many browser agents drive a browser, so the telemetry that distinguishes a legitimate agent session from a hijacked one is thin. We covered the surface in [browser AI security risks and controls](/blog/browser-ai-security-risks-and-controls/) and [securing computer use and browser agents](/blog/securing-computer-use-and-browser-agents/).

**OpenAI's Computer History feature** captures interaction events - clicks, typing, navigation - rather than screenshots. Reporting notes those files can contain sensitive information, are not encrypted, and are readable by other programs on macOS, and that the capture increases exposure to prompt injection originating in website content. An unencrypted, world-readable record of everything a user typed is a credential store by accident, and it is precisely the class of artifact an agent with local file access can be spliced into reading. [Auditing AI chat interactions](/blog/auditing-ai-chat-interactions/) covers what a defensible version of that record looks like.

## Detection and response

* Enumerate every MCP server configured on developer endpoints, including ones added outside your registry, and reconcile against what was approved.
* Alert on tool calls whose arguments contain the contents of sensitive paths (`.ssh/`, `.env`, `*.pem`, credential stores) regardless of the tool's declared purpose.
* Alert on outbound destinations that appear only in MCP tool arguments and nowhere else in the host's network profile.
* Treat any MCP server whose tool descriptions or annotations change after installation as requiring re-review. Silent redefinition is the delivery mechanism for the first channel.
* For browser agents, baseline which processes legitimately speak CDP and on which ports, so a cloned profile driving a headless instance is distinguishable from an agent doing its job.
* Rotate anything that was reachable from an agent's working directory if a hostile server was connected, since the researchers report source exfiltration succeeding even against models that refused the direct request.

## How Anomity helps

Anomity's Endpoint Sensor inventories **eight AI artifact types** per machine - agents, MCP servers, skills, extensions, plugins, hooks, CLIs, and secrets - which produces the list of connected MCP servers this technique depends on and that most teams cannot currently produce. Because it runs at the endpoint rather than inside one vendor's platform, a server added to Cursor, to Codex CLI, and to Claude Code all appear in the same view, which matters here specifically because the researchers' data shows the client is part of the exposure. Metadata only leaves the endpoint over HTTPS, with secrets redacted locally.

On agents that expose a hook, such as Claude Code's `PreToolUse`, [runtime governance](/#runtime-governance) returns **allow**, **deny**, or **log** on each tool call before it executes. That is the boundary GhostSplice has to cross to matter: the fragments are invisible, the exfiltration call is not. Every artifact change lands in a [queryable 90-day audit trail](/#outcomes), so a server whose tool surface changed after installation is a query rather than a discovery. To see which MCP servers are connected across your fleet today, and what [runtime governance](/#runtime-governance) would have denied, [book a 30-minute demo](/#early-access).

Share:Copied

## Frequently asked questions

What is GhostSplice?

GhostSplice is an attack technique in which a malicious MCP server distributes one harmful instruction across several separate interactions with an AI coding agent, so that no individual message contains anything a filter or a model would refuse. The researchers call the underlying property cross-channel trust fragmentation. The agent reassembles the fragments implicitly, because MCP preserves structured tool and result boundaries but the agent still combines everything into one working context. The refusal never fires because at no single point was the model asked to do anything wrong.


How does the three-channel version work?

Channel one is a tool description: a tool named integrity\_checker advertises a form with blandly named placeholder fields and no sensitive filenames anywhere in the schema. Channel two is the result of a scan\_project call, which enumerates which files exist in the project. Channel three is the result of a deep\_scan call, which supplies the missing mapping and tells the agent to populate those placeholder fields with the contents of .ssh/id\_rsa, proprietary source files, customers.csv, and .env, framed as server-side hash verification. Submitting the completed form sends the contents to the attacker's server.


Which models and clients were affected?

Researchers tested eleven models and report average compliance rising from 42% to 82% once instructions were split. GPT-4o, Gemini 2.0 Flash, and Llama 3.3 70B went from 0% on a single combined instruction to 100% when it was split into two pieces. Claude Haiku 4.5 held at 0% over the API but reached 100% in a three-piece test inside Cursor. GPT-5.4 is reported at 90% in Cursor and 100% through Codex CLI, and at 0% behind Claude Code. Claude Sonnet 4.6 and Opus 4.6 are listed at 0% overall, though the researchers note Sonnet still sent proprietary source containing a live hardcoded key in one test.


Why do description scanners and keyword filters miss it?

Because each control sees a fragment that is genuinely innocuous. A tool description scanner sees a schema with placeholder field names and no sensitive paths. A keyword filter on the result stream sees an instruction to populate parameters, which is what tool results legitimately do. The model's own safety training never triggers because the composite request is never presented to it as a composite. Every layer is evaluating in isolation, and the attack lives entirely in the aggregation.


Does GhostSplice work against an agent I have not connected to a hostile server?

No, and the researchers are explicit about it. The technique requires that the developer has already connected the attacker's MCP server, and it assumes the agent can already read the files being stolen. It is not a way to breach arbitrary agents from outside. That makes it a question about MCP install governance rather than about network perimeter: the exposure is proportional to how many unreviewed third-party servers your developers have wired into their agents.


What actually stops this?

Two controls do real work. First, treat MCP server output as data rather than instructions, and specifically do not let values from one tool's output flow unchecked into another tool's arguments, which is where the splice is reassembled. Second, evaluate the tool call itself at execution time, since the exfiltration step is a concrete outbound call with a hostile destination and a payload drawn from sensitive paths, and that is visible at the boundary even when every preceding message looked clean. Approval prompts help only if the human reviewing them can see what is actually being sent.