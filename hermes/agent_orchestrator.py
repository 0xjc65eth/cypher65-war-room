"""
HERMES Agent Orchestrator
=========================
Manages and calls specialized agents (MiningAgent, ProbabilityAgent, etc).
"""

from typing import Dict, Any, List, Optional


class AgentOrchestrator:
    """Orchestrates calls to specialized agents."""

    def __init__(self):
        self.agents: Dict[str, Any] = {}

    def register_agent(self, name: str, agent: Any):
        self.agents[name] = agent

    def call_agent(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        agent = self.agents.get(name)
        if not agent:
            return {"error": f"Agent {name} not found"}
        return agent.run(payload)

    def call_multiple(self, names: List[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        results = {}
        for name in names:
            results[name] = self.call_agent(name, payload)
        return results

    def list_agents(self) -> List[str]:
        return list(self.agents.keys())