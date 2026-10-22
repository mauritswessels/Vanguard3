"""Trading agents and the shared indicator library."""

from __future__ import annotations

from models.benchmark_agent import BuyHoldAgent
from models.equal_weight_agent import EqualWeightAgent
from models.learner_agent import LearnerAgent
from models.manager_agent import ManagerAgent
from models.monkey_agent import MonkeyAgent
from models.news_agent import NewsAgent, OpusNewsAgent
from models.opus_learner_agent import OpusLearnerAgent
from models.reversion_agent import ReversionAgent
from models.trend_agent import TrendAgent
from models.volatility_agent import VolatilityAgent

__all__ = ["AGENT_TYPES", "BuyHoldAgent", "EqualWeightAgent", "LearnerAgent", "ManagerAgent", "MonkeyAgent", "NewsAgent", "OpusNewsAgent", "OpusLearnerAgent", "ReversionAgent", "TrendAgent",
           "VolatilityAgent", "NEWS_KEYS", "CLAUDE_KEYS", "agent_key", "make_agent"]

#: Registry used to rebuild agents from saved state and config.
AGENT_TYPES = {
    "trend": TrendAgent,
    "reversion": ReversionAgent,
    "volatility": VolatilityAgent,
    "benchmark": BuyHoldAgent,
    "equal_weight": EqualWeightAgent,
    "learner": LearnerAgent,
    "learner_opus": OpusLearnerAgent,
    "news": NewsAgent,
    "news_opus": OpusNewsAgent,
    "monkey": MonkeyAgent,
    "manager": ManagerAgent,
}


#: Agents that read the news with Claude (evening and midday).
NEWS_KEYS = ("news", "news_opus")

#: Every agent that asks Claude each evening (the health check watches them).
CLAUDE_KEYS = NEWS_KEYS + ("learner_opus",)


def agent_key(agent) -> str:
    """Registry key of an agent instance."""
    for key, cls in AGENT_TYPES.items():
        if type(agent) is cls:
            return key
    raise KeyError(f"Unregistered agent type {type(agent).__name__}")


def make_agent(key: str, params: dict | None = None, learning: bool = False,
               name: str | None = None):
    """Instantiate a registered agent.

    ``params`` override the config defaults, ``learning`` turns on monthly
    self-tuning and ``name`` replaces the display name (used for twins).
    """
    cls = AGENT_TYPES[key]
    if key == "benchmark":
        agent = cls(**({"ticker": params["ticker"]} if params else {}))
    else:
        agent = cls(params)
    agent.learning = learning
    if name:
        agent.name = name
    return agent
