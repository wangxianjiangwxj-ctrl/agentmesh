"""
AgentMesh + CrewAI 集成示例
展示：在CrewAI工作流中使用AgentMesh保真度追踪和贡献度分配

安装依赖：
  pip install crewai agentmesh-sdk
"""

try:
    from crewai import Agent, Task, Crew, Process
    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    print("⚠️  CrewAI未安装。运行: pip install crewai")

import sys, os
# SDK路径：pip install agentmesh-sdk 后可移除以下两行
sys.path.insert(0, os.path.expanduser('~/.openclaw/skills/agentmesh-protocol/'))
from agentmesh_sdk import FidelityTracker, ContributionAllocator


def run_demo():
    print("=" * 60)
    print("AgentMesh + CrewAI 集成示例")
    print("=" * 60)
    print()

    # 演示数据：模拟CrewAI Agent输出
    steps = [
        {"agent": "researcher-alpha", "role": "调研员", "action": "调研AI Agent安全方向",
         "output": "发现3个研究方向", "fidelity": 0.9, "quality": 8.5},
        {"agent": "analyst-beta", "role": "分析师", "action": "分析调研结果",
         "output": "归类为2个核心方向", "fidelity": 0.65, "quality": 7.8},
        {"agent": "writer-gamma", "role": "撰稿人", "action": "输出综述报告",
         "output": "生成安全综述", "fidelity": 0.55, "quality": 7.2},
    ]

    print("[工作流] Researcher → Analyst → Writer")
    print()

    # 保真度追踪
    tracker = FidelityTracker(warning_threshold=0.5)
    allocator = ContributionAllocator()

    for s in steps:
        print(f"  [{s['role']}] {s['agent']}: {s['action']}")
        print(f"    产出: {s['output']}")
        print(f"    保真度: {s['fidelity']}")
        tracker.add_step(s["agent"], s["fidelity"], s["action"])
        allocator.add_claim(s["agent"], role_weight=1.0, task_completion=1.0, quality_score=s["quality"])
        print()

    # AgentMesh保真度报告
    print("[AgentMesh] 保真度追踪")
    print(f"  累积保真度: {tracker.cumulative_fidelity:.3f}")
    print(f"  警告触发: {tracker.cumulative_fidelity < 0.5}")
    print()

    print("[AgentMesh] 贡献度分配")
    shares = allocator.allocate()
    for agent, share in shares.items():
        print(f"  {agent}: {share:.1%}")
    print()

    print("CrewAI + AgentMesh 互补定位：")
    print("   CrewAI → 任务编排与Agent角色管理")
    print("   AgentMesh → 协作质量监控与贡献度量")
    print()

    if CREWAI_AVAILABLE:
        print("✅ CrewAI SDK已安装，可运行真实CrewAI工作流")
        print("   使用以下CrewAI结构集成AgentMesh：")
        print("""
    from crewai import Agent, Task, Crew, Process
    from agentmesh_sdk import FidelityTracker

    researcher = Agent(role='调研员', goal='调研信息', backstory='AI安全专家')
    task = Task(description='调研AI安全', agent=researcher)

    crew = Crew(agents=[researcher], tasks=[task], process=Process.sequential)
    result = crew.kickoff()

    # 用AgentMesh追踪保真度
    tracker = FidelityTracker()
    tracker.add_step('researcher', 0.9, 'CrewAI调研')
    print(f'保真度: {tracker.cumulative_fidelity}')
    """)
    else:
        print("⚠️  完整CrewAI集成需要: pip install crewai")


if __name__ == "__main__":
    run_demo()
