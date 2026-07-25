"""
Hermes Integration Layer
========================
Connects all components (Core, Agents, Tools, Probability Engine).
"""

from hermes.core import HermesCore
from hermes.intent import IntentEngine
from hermes.context import ContextOrchestrator
from hermes.memory import MemoryManager
from hermes.tool_registry import ToolRegistry
from hermes.agent_orchestrator import AgentOrchestrator

from hermes.agents.mining_agent import MiningAgent
from hermes.agents.probability_agent import ProbabilityAgent
from hermes.agents.financial_agent import FinancialAgent
from hermes.agents.rental_agent import RentalAgent
from hermes.agents.security_agent import SecurityAgent
from hermes.agents.performance_agent import PerformanceAgent
from hermes.agents.qa_agent import QAAgent
from hermes.agents.research_agent import ResearchAgent
from hermes.agents.product_agent import ProductAgent
from hermes.agents.redteam_agent import RedTeamAgent

from services.probability import calculate_block_probability


def build_hermes_system() -> HermesCore:
    """Build and wire the complete Hermes system."""

    core = HermesCore()
    intent_engine = IntentEngine()
    context_orchestrator = ContextOrchestrator()
    memory_manager = MemoryManager()
    tool_registry = ToolRegistry()
    agent_orchestrator = AgentOrchestrator()

    # Register agents
    probability_agent = ProbabilityAgent(calculate_block_probability)
    mining_agent = MiningAgent(probability_engine=calculate_block_probability)
    financial_agent = FinancialAgent()
    rental_agent = RentalAgent()
    security_agent = SecurityAgent()
    performance_agent = PerformanceAgent()
    qa_agent = QAAgent()
    research_agent = ResearchAgent()
    product_agent = ProductAgent()
    redteam_agent = RedTeamAgent()

    agent_orchestrator.register_agent("MiningAgent", mining_agent)
    agent_orchestrator.register_agent("ProbabilityAgent", probability_agent)
    agent_orchestrator.register_agent("FinancialAgent", financial_agent)
    agent_orchestrator.register_agent("RentalAgent", rental_agent)
    agent_orchestrator.register_agent("SecurityAgent", security_agent)
    agent_orchestrator.register_agent("PerformanceAgent", performance_agent)
    agent_orchestrator.register_agent("QAAgent", qa_agent)
    agent_orchestrator.register_agent("ResearchAgent", research_agent)
    agent_orchestrator.register_agent("ProductAgent", product_agent)
    agent_orchestrator.register_agent("RedTeamAgent", redteam_agent)

    # Attach to core
    core.intent_engine = intent_engine
    core.context_orchestrator = context_orchestrator
    core.memory_manager = memory_manager
    core.tool_registry = tool_registry
    core.agent_orchestrator = agent_orchestrator

    return core


# Global instance
hermes = build_hermes_system()