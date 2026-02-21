"""Backward-compatible shim for the legacy LLM client module.

.. deprecated:: 0.2.0
    Import from ``emet.cognition.llm_factory`` or ``emet.cognition.llm_base``
    instead.  This module re-exports the old names so existing code
    (``agent.py``) doesn't break during transition.
"""

from __future__ import annotations

# Re-export everything callers expect from the old module
from emet.cognition.llm_base import LLMResponse  # noqa: F401
from emet.cognition.llm_anthropic import AnthropicClient  # noqa: F401
from emet.cognition.llm_factory import (  # noqa: F401
    create_llm_client_sync as create_llm_client,
)

__all__ = ["LLMResponse", "AnthropicClient", "create_llm_client"]
