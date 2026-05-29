# Reddit 发布文案（AgentMesh v0.3）

> 配合 HN 发布，同步在 r/MachineLearning / r/Python 发布

---

## r/MachineLearning — [D] Multi-agent information decay: we quantified it

标题:
We ran 9 experiments on multi-agent collaboration and found 50%+ information loss across 3 hops

正文:

I've been building multi-agent systems with LangGraph, CrewAI, and AutoGen. One thing kept bugging me: when Agent A talks to Agent B, who talks to Agent C, does the original information survive?

Turns out, it doesn't — and without tracking tools, you'd never know.

I built AgentMesh, an open-source Python SDK, to quantify this:
- Fidelity tracking: measure information decay per agent hop
- Contribution allocation: attribute output to the right agent
- L1 message templates: structural guarantees for message format
- A2A adapter: works with any A2A-compatible agent

We ran **9 controlled experiments** and here's what we found:
- 100% message format conflicts without templates (vs 0% with)
- 3 critical omissions in the control group (vs 0 with structured templates)
- Cumulative fidelity drops to 0.585 after just 2 hops (40%+ info loss)
- Reviewer agents caught 4/4 injected reasoning errors (100% detection rate)

The code is on GitHub with 9 experiment scripts, 50+ tests, and full docs:
https://github.com/wangxianjiangwxj-ctrl/agentmesh

pip install agentmesh-sdk

Would love feedback from anyone who's dealt with multi-agent reliability issues.

---

## r/Python — Show & Tell

标题:
AgentMesh: Open-source fidelity tracking for multi-agent Python systems

正文:

I built a Python library to solve a problem I kept running into: when multiple agents communicate (via A2A protocol), how do you know information isn't being lost or distorted?

AgentMesh provides:
- FidelityTracker: measures semantic preservation across hops (0.0-1.0)
- ContributionAllocator: traces which agent contributed what
- A2AAdapter: plug into any A2A-compatible agent (LangGraph, CrewAI)
- Message templates: structural contracts between agents

Key numbers from 9 experiments:
- 40%+ information loss after 2 agent hops without tracking
- 0% format conflicts with structured templates (vs 100% without)
- 100% reasoning error detection rate with reviewer agents

GitHub: https://github.com/wangxianjiangwxj-ctrl/agentmesh
PyPI: pip install agentmesh-sdk

Static site with examples: https://wangxianjiangwxj-ctrl.github.io/agentmesh/

---

## r/LocalLLaMA — Technical

标题:
Quantifying information decay in multi-agent local LLM chains

正文:

If you're running multi-agent chains with local LLMs (via Ollama/LM Studio), you might wonder: does the original instruction survive after 3 agent hops?

I ran experiments with AgentMesh's FidelityTracker and found:
- 2 hops → fidelity drops to ~0.585
- Without structured templates, format conflicts in ALL cases
- Reviewer agents (also local) can detect reasoning errors at 100% rate

This is especially important for local LLM setups where each model might interpret/truncate/rephrase the input differently.

Full write-up + code: https://github.com/wangxianjiangwxj-ctrl/agentmesh
