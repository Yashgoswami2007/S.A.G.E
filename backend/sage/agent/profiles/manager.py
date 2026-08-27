from typing import Dict
from sage.agent.profiles.base import AgentProfile
from sage.tools.base import ToolPermission

class ProfileManager:
    def __init__(self):
        self._profiles: Dict[str, AgentProfile] = {}
        self._register_default_profiles()

    def _register_default_profiles(self):
        # 1. Analyst: Safe read-only tools + reasoning model
        self._profiles["analyst"] = AgentProfile(
            name="analyst",
            description="Document & data analysis profile (read-only tools)",
            model_preference="reasoning",
            max_permission=ToolPermission.SAFE,
            allowed_tools={"read_file", "list_dir", "search_files", "get_file_info"}
        )

        # 2. Coder: All 7 tools + coding model
        self._profiles["coder"] = AgentProfile(
            name="coder",
            description="Software engineering & automation profile (full tool access)",
            model_preference="coding",
            max_permission=ToolPermission.HIGH_RISK,
            allowed_tools={
                "read_file", "write_file", "list_dir",
                "search_files", "get_file_info", "apply_patch", "execute_command"
            }
        )

        # 3. Inspector: Safe read-only tools + vision model
        self._profiles["inspector"] = AgentProfile(
            name="inspector",
            description="Visual inspection & multimodal report profile (read-only tools)",
            model_preference="vision",
            max_permission=ToolPermission.SAFE,
            allowed_tools={"read_file", "list_dir", "search_files", "get_file_info"}
        )

        # 4. General: Safe tools by default + reasoning model
        self._profiles["general"] = AgentProfile(
            name="general",
            description="General purpose assistant (safe tools)",
            model_preference="reasoning",
            max_permission=ToolPermission.SAFE,
            allowed_tools={"read_file", "list_dir", "search_files", "get_file_info"}
        )

    def get_profile(self, name: str) -> AgentProfile:
        """Returns profile by name, falling back to 'general'."""
        return self._profiles.get(name.lower(), self._profiles["general"])
