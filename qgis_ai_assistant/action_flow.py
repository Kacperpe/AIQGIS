"""
action_flow.py
--------------
Odpowiada za:
  - sanityzacje surowego tekstu modelu (usuwa wycieki JSON, <|channel|> itp.)
  - wykrywanie propozycji akcji (bloki kodu) i budowanie ActionProposal
  - przechowywanie sesyjnych zgod uzytkownika (PermissionStore)
  - decydowanie czy tool moze wykonac sie od razu (ToolExecutionGuard)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Stale - klasyfikacja narzedzi
# ---------------------------------------------------------------------------

READ_ONLY_TOOLS = {
    "list_layers",
    "get_project_info",
    "get_active_layer_info",
    "get_selected_features_info",
    "get_fields",
    "get_project_crs",
    "get_layer_crs",
    "get_unique_values",
    "summarize_field",
    "validate_layer",
    "get_layer_details",
}

SAFE_UI_TOOLS = {
    "zoom_to_layer",
    "zoom_to_selection",
    "refresh_canvas",
    "preview_action",
    "log_message",
    "show_message_bar",
}

# Te narzedzia ZAWSZE wymagaja zgody uzytkownika
CONFIRMATION_REQUIRED_TOOLS = {
    "insert_into_pyqgis_console",
    "run_pyqgis_code",
}

ACTION_PROPOSAL_TOOLS = {
    "generate_pyqgis_code",
    "insert_into_pyqgis_console",
    "run_pyqgis_code",
}

# Wzorce smieci, ktore model czasem puszcza do UI
_NOISE_PATTERNS = [
    r"<\|channel\|>.*?(?=\n|$)",
    r"to=functions\s*commentary\?\{.*?\}",
    r"commentary\s*to=functions.*?(?=\n|$)",
    r'\{"ok"\s*:\s*(true|false)[^}]*\}',
    r"final\{.*?\}",
    r"System:\s*Narzedzie QGIS:.*?(?=\n|$)",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# ActionProposal
# ---------------------------------------------------------------------------

@dataclass
class ActionProposal:
    response_type: str = "message"
    title: str = ""
    summary: str = ""
    code: str = ""
    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    requires_confirmation: bool = False
    operation_signature: str = ""
    content: str = ""


# ---------------------------------------------------------------------------
# PermissionStore
# ---------------------------------------------------------------------------

class PermissionStore:
    def __init__(self) -> None:
        self.allow_all: bool = False
        self._session_signatures: set = set()

    def approve_for_session(self, signature: str) -> None:
        self._session_signatures.add(signature)

    def approve_all(self) -> None:
        self.allow_all = True

    def is_allowed(self, signature: str) -> bool:
        return self.allow_all or signature in self._session_signatures

    def reset(self) -> None:
        self.allow_all = False
        self._session_signatures.clear()


# ---------------------------------------------------------------------------
# LLMResponseParser
# ---------------------------------------------------------------------------

class LLMResponseParser:

    def sanitize(self, text: str) -> str:
        cleaned = _NOISE_RE.sub("", text or "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def extract_code(self, text: str) -> str:
        m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def strip_code_blocks(self, text: str) -> str:
        return re.sub(
            r"```(?:python)?\s*.*?```", "", text,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()

    def assess_risk(self, code: str = "", tool_name: str = "") -> str:
        HIGH = [
            "os.remove", "shutil.", "subprocess", "eval(", "exec(",
            "requests.", "urllib.request", "deletefeatures", "removemaplayer",
            "QgsProject.instance().clear",
        ]
        MEDIUM = [
            "addmaplayer", "startediting", "commitchanges",
            "writeasvectorformat", "QgsVectorFileWriter",
            "insert_into_pyqgis_console", "run_pyqgis_code",
        ]
        if tool_name in {"run_pyqgis_code"}:
            return "high"
        if tool_name in {"insert_into_pyqgis_console", "generate_pyqgis_code"}:
            return "medium"
        code_l = code.lower()
        if any(m in code_l for m in HIGH):
            return "high"
        if any(m in code_l for m in MEDIUM):
            return "medium"
        return "low"

    def build_signature(
        self,
        tool_name: str = "",
        tool_args: Optional[Dict[str, Any]] = None,
        summary: str = "",
    ) -> str:
        tool_args = tool_args or {}
        task_text = (
            summary
            or tool_args.get("task_description")
            or tool_args.get("action_label")
            or tool_args.get("expression")
            or ""
        )
        code_hint_lines = str(tool_args.get("code") or "").strip().splitlines()[:1]
        code_hint = code_hint_lines[0] if code_hint_lines and not task_text else ""
        normalized = {
            "tool": tool_name,
            "layer_name": tool_args.get("layer_name", ""),
            "input_layer_name": tool_args.get("input_layer_name", ""),
            "input_layers": sorted(
                tool_args.get("input_layers", []) or tool_args.get("target_layers", [])
            ),
            "overlay_layer_name": tool_args.get("overlay_layer_name", ""),
            "target_crs": tool_args.get("target_crs", ""),
            "output_name": tool_args.get("output_name", ""),
            "task": str(task_text)[:200].strip().lower(),
            "code_hint": code_hint[:120].strip().lower(),
        }
        payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    def parse(
        self,
        model_text: str,
        last_tool_name: Optional[str] = None,
        last_tool_args: Optional[Dict[str, Any]] = None,
    ) -> ActionProposal:
        last_tool_args = last_tool_args or {}
        clean = self.sanitize(model_text)
        code = self.extract_code(clean)

        if code or last_tool_name in CONFIRMATION_REQUIRED_TOOLS:
            summary = self.strip_code_blocks(clean) if code else clean
            risk = self.assess_risk(code=code, tool_name=last_tool_name or "")
            sig = self.build_signature(
                tool_name=last_tool_name or "pyqgis_code",
                tool_args=last_tool_args,
                summary=summary,
            )
            return ActionProposal(
                response_type="action_proposal",
                title="Proponowana akcja",
                summary=summary or "AI przygotowalo operacje do wykonania.",
                code=code,
                tool_name=last_tool_name,
                tool_args=last_tool_args,
                risk_level=risk,
                requires_confirmation=True,
                operation_signature=sig,
            )

        return ActionProposal(
            response_type="message",
            content=clean or "Brak odpowiedzi.",
        )


# ---------------------------------------------------------------------------
# ToolExecutionGuard
# ---------------------------------------------------------------------------

class ToolExecutionGuard:

    def __init__(self, permission_store: PermissionStore) -> None:
        self.perms = permission_store

    def may_execute_immediately(self, tool_name: str, signature: str = "") -> bool:
        if tool_name in READ_ONLY_TOOLS:
            return True
        if tool_name in SAFE_UI_TOOLS:
            return True
        if tool_name in CONFIRMATION_REQUIRED_TOOLS:
            return self.perms.is_allowed(signature)
        return self.perms.allow_all or self.perms.is_allowed(signature)
