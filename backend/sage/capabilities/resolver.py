import logging
from typing import Optional, Dict
from sage.tools.registry import ToolRegistry

logger = logging.getLogger("sage.capabilities.resolver")

class CapabilityResolver:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        
    def resolve(self, capability: str) -> Optional[str]:
        """
        Given a capability description, tries to find a registered tool that fulfills it.
        Returns the name of the tool if found, otherwise None.
        """
        # First check dynamic tools which explicitly have a 'capability' attached to their spec
        for tool in self.registry._tools.values():
            if hasattr(tool, "spec") and getattr(tool.spec, "capability", "") == capability:
                return tool.name
                
        # We could also use LLM to semantic match existing tools here if desired.
        # For now, it relies on explicit capability mapping or tool composition.
        return None
