"""Trading agents and the shared indicator library."""

from __future__ import annotations

from models.benchmark_agent import BuyHoldAgent
from models.reversion_agent import ReversionAgent
from models.trend_agent import TrendAgent
from models.volatility_agent import VolatilityAgent

__all__ = ["AGENT_TYPES", "BuyHoldAgent", "ReversionAgent", "TrendAgent",
           "VolatilityAgent", "agent_key", "make_agent"]

#: Registry used to rebuild agents from saved state and config.
AGENT_TYPES = {
    "trend": TrendAgent,
    "reversion": ReversionAgent,
    "volatility": VolatilityAgent,
    "benchmark": BuyHoldAgent,
}


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
