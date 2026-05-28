# Hacker News 发布文案

## 标题（选一个）

**方案A（数据驱动）**：
We ran 9 experiments on multi-agent collaboration. Over 50% of information was lost in 3 hops.

**方案B（痛点驱动）**：
Your agents are losing information — and you don't know it. Here's how we quantified it.

**方案C（定位驱动）**：
AgentMesh: Open-source fidelity tracking for multi-agent systems. A2A lets agents talk, AgentMesh ensures nothing gets lost.

**推荐**：方案A — 具体数字+实验结果在HN上效果好。

## 正文

Multi-agent systems (LangGraph, CrewAI, AutoGen) let agents communicate, but they don't track whether information is preserved across hops.

We ran 9 experiments to quantify this. Key findings:
- 100% message format conflicts without templates (vs 0% with)
- 3 critical omissions in the control group (vs 0 with structured templates)
- Cumulative fidelity drops to 0.585 after just 2 hops (40%+ information loss)
- Reviewer agents caught 4/4 injected reasoning errors (100% detection rate)

AgentMesh is an open-source Python SDK that adds:
- Fidelity tracking (see how much information decays per hop)
- Contribution allocation (who contributed what)
- L1 message templates (eliminate format conflicts)
- A2A adapter (interoperate with any A2A-compatible agent)

GitHub: [link]
Install: pip install agentmesh-sdk

Built 9 experiments, 50+ tests, full documentation, Web demo all available.

## 第一句话（用于HN标题下的描述）

"50%+ information loss across 3-agent hops is invisible without tracking tools. We built an open-source solution."

---

## 知乎发布文案

**标题**：
多Agent协作超过一半信息在传递中丢失？我们用9轮实验量化了这个衰减

**正文**：
（直接使用中文博客正文，添加链接）
