---
来源: https://deniskim1.com/writing/llm_red_teaming_ctf_20_levels/
类型: html
获取日期: 2026-06-30
---

Almost everything written about prompt injection is written in the abstract. You read that XML delimiters are not a security boundary, that keyword filters fail against paraphrase, that an output classifier can be walked around — and then you close the tab, having learned a claim rather than a skill.

The gap is that the claims are easy to state and hard to feel. Knowing "delimiters are not a trust boundary" is not the same as sitting in front of a model, spending eleven turns failing to get out of a fenced code block, and discovering on the twelfth what actually moves it.

So I built somewhere to close that gap: **[a 20-level LLM red-teaming CTF](/ctf/)**, live, free, and running against a real model rather than a scripted mock. No signup, no email, no account. Open the page and you have a session.

---

## What it actually is

Twenty levels across four tiers. Each level is a system prompt holding a secret flag, plus some defensive apparatus wrapped around it. Your job is to make the model give up the flag anyway, then submit it.

| Tier | Levels | Theme |
| --- | --- | --- |
| 1 | 1–5 | **Fundamentals** — XML boundaries, persona locks, roleplay, summarizer context, cross-lingual alignment gaps |
| 2 | 6–10 | **Filters & Encoding** — regex WAFs, punctuation stripping, egress DLP, ciphers, an intent-classifier pre-filter |
| 3 | 11–15 | **Structural Evasion** — code-fence escape, JSON envelope breakout, role-marker confusion, privilege framing, indirect RAG |
| 4 | 16–20 | **Advanced Evasion** — tool-call forgery, output-classifier evasion, dual-LLM peer review, attachment injection, a 3-agent pipeline |

The target is **qwen3:8b** running on a Mac Mini in my apartment. That matters for two reasons. First, nothing here is faked: when the model refuses, it is genuinely refusing, and when it leaks, you genuinely broke it. Second, an 8B model is a *forgiving* adversary — it is exactly the size where the attacks in the literature are reproducible by hand rather than requiring a research budget. You will succeed often enough to learn the shape of each technique.

Eighteen of the twenty levels are **multi-turn**: conversation history is replayed, so you can groom the model across several messages rather than landing everything in one payload. Two levels deliberately disable history, because their entire mechanic is that your single payload sits *inside* a structure you have to escape — replayed history would hand you somewhere to write outside the fence and delete the level.

---

## What each tier is actually teaching

**Tier 1** is where you learn that natural-language prohibition is not enforcement. Level 1 wraps the secret in `<system_policy>` tags and instructs the model, in plain English, never to reveal, paraphrase, translate, split, or encode it. Level 2 adds a persona lock and refuses hypotheticals. Level 5 forbids disclosure "in any language or translation" — and then you find out how evenly that alignment is actually distributed across languages.

The lesson of Tier 1 is not that these defenses are weak in some subtle way. It is that they are *instructions*, and instructions are the thing you are attacking.

**Tier 2** moves the defense out of the prompt and onto the server, where it becomes real code. Level 6 puts a regex WAF in front of the model that drops any message containing `flag`, `secret`, `ignore`, `reveal`, `system`, `key`, or `pass` — blocked messages never reach the model at all. Level 7 strips every non-alphanumeric character from your input, so you write your injection with letters, digits, and spaces only. Levels 8 and 9 flip the direction entirely: an egress DLP filter redacts the flag from the *response*, including spaced, hyphenated, and line-split renderings of it, so cleartext is off the table and you have to get the model to re-encode.

This is where the interesting asymmetry shows up. The WAF scores each message independently and has no memory; the model has memory. That gap is the level.

**Tier 3** attacks structure rather than semantics. Your input gets placed inside a markdown code fence, or interpolated into a JSON envelope, or appended to a chat buffer with `<|im_start|>` role markers, or retrieved as "Document 42" next to a document containing the key. These are the levels that generalise most directly to production systems, because every real deployment concatenates untrusted text into *some* template, and the template is usually the only thing separating instructions from data.

**Tier 4** is where the defenses stop being single components. Level 17 puts a second classifier in front of every response, one that is blind to the secret and only sees the output. Level 18 runs a full generator/reviewer pair: Model A holds the flag, Model B inspects A's output for policy violations, and only approved answers reach you — so you have to make one model leak in a form the other model approves. Level 20 chains a Planner, a Worker holding the flag, and a Sentinel enforcing boundaries, and asks you to escalate across all three.

Every level, once solved, unlocks a write-up mapping it to the **OWASP LLM Top 10** category it exercises, with the real-world failure mode and the mitigation that would actually have stopped it. LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, and LLM07 System Prompt Leakage all show up repeatedly, which is itself the point.

---

## The part I did not expect to have to build

The most instructive engineering in this project is not any level. It is the scorer.

Scoring "did the attacker win?" is a judgement call, so there is an LLM judge behind it. And an LLM judge sitting downstream of an attacker's raw text is *itself an injection target* — a fact I had read many times and still managed to build wrong.

Three things went wrong, and they are worth naming because they are all generic:

**The judge never spoke.** qwen3 is a reasoning model whose thinking tokens are drawn from the same generation budget as its answer. The judge was called with an 80-token budget; reasoning alone consumed 45–160. Across 24 measured trials, the judge returned a parseable verdict **zero** times. Every `judge_criteria` string in the level definitions was decorative, and the only functioning scorers were three literal string matchers. A component can be entirely absent from production and still look present in the code.

**The judge was injectable.** The attacker's text was spliced into the judge's prompt with no delimiter. Once the judge could actually speak, a payload instructing it to return a winning verdict worked 5 times out of 5.

**The judge leaked the answer.** Its system prompt contained the expected flag so it could compare, and its free-text reason was rendered back to the player on a loss. A payload that made the judge quote the flag into that reason field let the player simply read the flag off the screen. Also 5 out of 5.

The fixes shipped together, because any one alone would have armed the others: thinking disabled on every model call, the attacker's text fenced and the flag redacted inside the judge prompt, a one-word verdict channel with no JSON structure to forge, and a **closed enum** of reason strings so that no model-generated text ever crosses the API boundary to the player.

That last one is the transferable lesson. The durable fix was not a better prompt for the judge. It was removing the channel through which judge output could reach the user at all.

---

## Some design decisions you can steal

**Flags are per-session and unforgeable.** Each flag is `CTF{...}` over an HMAC-SHA256 of `user_id : level_N : flag_seed`, where the seed is a server-side uuid4. Your flag for level 7 is not my flag for level 7, so there is no answer key to share and nothing to look up. It also means a leaked signing key alone does not let anyone forge flags — they would need the per-session seed too.

**Guardrails that can be deterministic, are.** The WAF blacklist, the punctuation stripper, and the egress DLP redactor are plain regex, not model calls. Only the levels whose *mechanic is a classifier* — the Tier 2 pre-filter, the Tier 4 output reviewer — spend an inference. On a single-GPU machine every avoided model call is latency returned to the player.

**Hints are earned, not offered.** The first hint unlocks after 8 attempts on multi-turn levels, the second after 14. On the two single-turn levels the thresholds drop to 3 and 5, because there a legitimate grooming sequence is not available to you. The hints teach strategy — *payload splitting*, *crescendo*, *few-shot capability priming* — rather than handing over a working string.

---

## Practical notes before you start

It runs on one consumer GPU that has a higher-priority tenant, so: inference is serialized, the queue is shallow, and the chat endpoint is rate-limited to 10 messages a minute. If you hit a busy notice, wait a moment rather than retrying hard. First response after an idle period can be slow while the model loads.

Sessions persist for 7 days and survive private/incognito windows. Clear a level's conversation whenever a line of attack has poisoned the context — a model that has refused you six times is measurably harder to move than a fresh one, which is itself a finding worth having.

Finish all twenty and you get a signed completion certificate.

Two honest caveats. This is a teaching instrument, not a benchmark: an 8B local model is more permissive than a frontier model behind a production safety stack, and solving level 18 here does not mean you can defeat a real dual-LLM deployment. And the techniques are the standard published ones — nothing here is novel offense. What is novel, for most people, is doing it with their own hands.

**[Start at level 1 →](/ctf/)**

If you break something in a way the level did not anticipate, or find a flag path I did not intend, I would genuinely like to hear about it.