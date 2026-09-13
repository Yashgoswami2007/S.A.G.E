from typing import Dict
from sage.agent.profiles.base import AgentProfile
from sage.tools.base import ToolPermission

class ProfileManager:
    def __init__(self):
        self._profiles: Dict[str, AgentProfile] = {}
        self._register_default_profiles()

    def _register_default_profiles(self):
        # 1. Analyst: Document & data analysis with RAG access
        self._profiles["analyst"] = AgentProfile(
            name="analyst",
            description="Document & data analysis profile (RAG + read-only workspace tools)",
            model_preference="reasoning",
            max_permission=ToolPermission.MODIFY,
            allowed_tools={"read_file", "list_dir", "search_files", "get_file_info", "rag_search", "rag_ingest"}
        )

        # 2. Coder: All tools + coding model
        self._profiles["coder"] = AgentProfile(
            name="coder",
            description="Software engineering & automation profile (full tool access)",
            model_preference="coding",
            max_permission=ToolPermission.HIGH_RISK,
            allowed_tools={
                "read_file", "write_file", "list_dir",
                "search_files", "get_file_info", "apply_patch", "execute_command",
                "rag_search", "rag_ingest"
            }
        )

        # 3. Inspector: Safe read-only tools + RAG + vision model
        self._profiles["inspector"] = AgentProfile(
            name="inspector",
            description="Visual inspection & multimodal report profile (read-only tools + RAG)",
            model_preference="vision",
            max_permission=ToolPermission.SAFE,
            allowed_tools={"read_file", "list_dir", "search_files", "get_file_info", "rag_search"}
        )

        # 4. General: Safe tools by default + RAG + reasoning model
        self._profiles["general"] = AgentProfile(
            name="general",
            description="General purpose assistant (safe tools + RAG)",
            model_preference="reasoning",
            max_permission=ToolPermission.SAFE,
            allowed_tools={"read_file", "list_dir", "search_files", "get_file_info", "rag_search"}
        )

    def get_profile(self, name: str) -> AgentProfile:
        """Returns profile by name, falling back to 'general'."""
        return self._profiles.get(name.lower(), self._profiles["general"])
