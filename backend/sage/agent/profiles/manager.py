from typing import Dict
from sage.agent.profiles.base import AgentProfile
from sage.tools.base import ToolPermission

class ProfileManager:
    def __init__(self):
        self._profiles: Dict[str, AgentProfile] = {}
        self._register_default_profiles()

    def _register_default_profiles(self):
        # 1. Analyst: Read + document generation tools + reasoning model
        self._profiles["analyst"] = AgentProfile(
            name="analyst",
            description="Document & data analysis profile (read + document generation tools)",
            model_preference="reasoning",
            max_permission=ToolPermission.MODIFY,
            allowed_tools={
                "read_file", "list_dir", "search_files", "get_file_info",
                "read_pdf", "read_docx", "read_xlsx", "read_image", "ocr_extract",
                "calculator", "rag_search",
                "generate_docx", "generate_xlsx", "generate_pdf",
            }
        )

        # 2. Coder: All tools + coding model
        self._profiles["coder"] = AgentProfile(
            name="coder",
            description="Software engineering & automation profile (full tool access)",
            model_preference="coding",
            max_permission=ToolPermission.HIGH_RISK,
            allowed_tools={
                "read_file", "write_file", "list_dir",
                "search_files", "get_file_info", "apply_patch",
                "execute_command", "execute_code", "run_script",
                "read_pdf", "read_docx", "read_xlsx", "read_image", "ocr_extract",
                "generate_docx", "generate_xlsx", "generate_pptx", "generate_pdf",
                "calculator", "synthesize_capability", "rag_search",
            }
        )

        # 3. Inspector: Read + vision/OCR tools + vision model
        self._profiles["inspector"] = AgentProfile(
            name="inspector",
            description="Visual inspection & multimodal report profile (read + OCR + doc gen)",
            model_preference="vision",
            max_permission=ToolPermission.MODIFY,
            allowed_tools={
                "read_file", "list_dir", "search_files", "get_file_info",
                "read_pdf", "read_image", "ocr_extract",
                "generate_docx", "generate_pdf",
            }
        )

        # 4. Documentor: Read + all document generation tools
        self._profiles["documentor"] = AgentProfile(
            name="documentor",
            description="Document generation profile (read + generate Word/Excel/PPTX)",
            model_preference="reasoning",
            max_permission=ToolPermission.MODIFY,
            allowed_tools={
                "read_file", "list_dir", "search_files", "get_file_info",
                "read_pdf", "read_docx", "read_xlsx", "read_image", "ocr_extract",
                "calculator", "rag_search",
                "generate_docx", "generate_xlsx", "generate_pptx", "generate_pdf",
            }
        )

        # 5. General: Read + utility + execution tools + reasoning model
        #    execute_command / execute_code / run_script are HIGH_RISK and
        #    still require explicit user approval via the executor's approval gate.
        self._profiles["general"] = AgentProfile(
            name="general",
            description="General purpose assistant (read + utility + execution tools)",
            model_preference="reasoning",
            max_permission=ToolPermission.HIGH_RISK,
            allowed_tools={
                "read_file", "list_dir", "search_files", "get_file_info",
                "read_pdf", "read_docx", "read_xlsx", "read_image", "ocr_extract",
                "calculator", "rag_search",
                "execute_command", "execute_code", "run_script",
            }
        )

    def get_profile(self, name: str) -> AgentProfile:
        """Returns profile by name, falling back to 'general'."""
        return self._profiles.get(name.lower(), self._profiles["general"])
