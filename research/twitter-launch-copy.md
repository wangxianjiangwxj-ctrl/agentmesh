# Twitter/X 发布文案（AgentMesh v0.3）

> 配合 HN/Reddit 发布，发一个 6 条线程

---

Thread (6 tweets):

1/ Your multi-agent system is leaking information — and you don't know it.

We ran 9 controlled experiments on agent-to-agent communication.

Results: 50%+ information loss after just 3 hops.

Here's what we found:

2/ The problem isn't that agents can't talk. A2A protocol solves that.

The problem: once they talk, you have NO visibility into what got lost.

One agent rephrases. Another truncates. A third makes assumptions.

Each hop = information decay.

3/ We built AgentMesh to fix this.

An open-source Python SDK that tracks:

- Fidelity: measure information preservation per hop (0.0-1.0)
- Contribution: attribute output to the right agent
- Templates: structural guarantees between agents
- A2A adapter: plug into LangGraph, CrewAI, AutoGen

4/ From 9 experiments:

- Format conflicts: 100% without templates → 0% with ✅
- Critical omissions: 3 in control → 0 with structured templates ✅
- Reasoning errors: 4/4 caught by reviewer agents ✅
- Fidelity after 2 hops: 0.585 — that's ~40% loss

5/ The key insight: tracking doesn't just measure decay — it prevents it.

When agents use structured message templates + fidelity-aware routing, the entire system becomes more reliable.

You can't improve what you can't measure.

6/ Open source. MIT license. 50+ tests. Full documentation.

GitHub: github.com/wangxianjiangwxj-ctrl/agentmesh

Install: pip install agentmesh-sdk

Web demo + experiments: wangxianjiangwxj-ctrl.github.io/agentmesh

Built with A2A protocol. Works with any A2A-compatible agent.

---

## 替代方案（中文短版本 — 知乎预热）

Thread (4 tweets):

1/ 多 Agent 协作时，信息在传递中会丢失多少？我们用 9 轮实验测了一下。

结果：3 跳后信息丢失超过 50%。

2/ 问题不在于 Agent 能不能通信（A2A 协议解决了这个），而在于通信后你不知道丢了什么。

一个 Agent 改写 → 另一个截断 → 第三个加入自己的假设 → 原始信息早已面目全非。

3/ 我们做了 AgentMesh 来解决：
- FidelityTracker: 量化每跳信息保真度
- ContributionAllocator: 归因每个 Agent 的贡献
- 消息模板: 结构化的 agent 间通信契约
- 兼容 A2A 协议，支持 LangGraph/CrewAI/AutoGen

4/ 开源 MIT，pip install agentmesh-sdk

GitHub: github.com/wangxianjiangwxj-ctrl/agentmesh

9 个实验脚本 + 50+ 测试 + 完整文档。

多 Agent 系统的可观测性，不应该是一个奢侈品。
