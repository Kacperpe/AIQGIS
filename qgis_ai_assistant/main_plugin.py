import html
import json

from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QPushButton, QTextBrowser,
    QVBoxLayout, QWidget,
)

from .claude_client import ClaudeClient
from .worker import Worker
from . import qgis_tools


def html_escape_code(text):
    code = text.strip("\n")
    if "\n" in code:
        first_line, rest = code.split("\n", 1)
        stripped = first_line.strip()
        # strip language hint line (e.g. ```python)
        if stripped and stripped.replace("_", "").isalnum():
            code = rest
    return html.escape(code)


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

class AIPanel(QWidget):
    def __init__(self, plugin, api_key: str):
        super().__init__()
        self.plugin = plugin
        self.iface = plugin.iface
        self.worker = None
        self.client = ClaudeClient(api_key)
        self._build_ui()
        self._welcome()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Chat display — QTextBrowser renders HTML and supports anchor clicks
        self.chat = QTextBrowser()
        self.chat.setReadOnly(True)
        self.chat.setOpenLinks(False)
        self.chat.setStyleSheet(
            "QTextBrowser { background:#1e1e1e; color:#d4d4d4; "
            "font-family: Consolas, monospace; font-size:12px; }"
        )
        root.addWidget(self.chat)

        # Toolbar buttons
        btn_row = QHBoxLayout()
        for label, slot in [
            ("API Key",     self._change_api_key),
            ("Layers",      self._inject_layers),
            ("CRS",         self._inject_crs),
            ("Layer Info",  self._inject_layer_info),
            ("Selected",    self._inject_selected),
            ("Extent",      self._inject_extent),
            ("Clear",       self._clear),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        # Input row
        send_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask about your GIS data or request an operation…")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedWidth(80)
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.input)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

        self.status = QLabel("")
        self.status.setStyleSheet("color: gray; font-size: 10px;")
        root.addWidget(self.status)

    # ------------------------------------------------------------------
    # Chat rendering
    # ------------------------------------------------------------------

    def _welcome(self):
        self._append(
            "system",
            "AI GIS Agent ready. I can list layers, run processing algorithms, "
            "load files, and perform GIS operations directly in your project.",
        )

    def _append(self, role: str, text: str):
        colours = {
            "user":      "#569cd6",
            "assistant": "#4ec9b0",
            "system":    "#808080",
            "error":     "#f44747",
            "tool":      "#ff9800",
        }
        labels = {
            "user":      "You",
            "assistant": "AI",
            "system":    "System",
            "error":     "Error",
            "tool":      "🔧 Tool",
        }
        colour = colours.get(role, "#ffffff")
        label  = labels.get(role, role)

        parts = text.split("```")
        msg_html = (
            f'<span style="color:{colour};font-weight:bold">'
            f'{html.escape(label)}:</span> '
        )
        for i, part in enumerate(parts):
            if i % 2 == 1:
                escaped = html_escape_code(part)
                msg_html += (
                    "<br><pre style=\"background:#2d2d2d;color:#ce9178;"
                    "padding:6px;border-radius:4px;white-space:pre-wrap\">"
                    f"{escaped}</pre>"
                )
            else:
                msg_html += html.escape(part).replace("\n", "<br>")

        self.chat.append(msg_html + "<br>")
        self.chat.moveCursor(QTextCursor.End)

    # ------------------------------------------------------------------
    # Context-injection helpers
    # ------------------------------------------------------------------

    def _inject_layers(self):
        from qgis.core import QgsProject

        layers = list(QgsProject.instance().mapLayers().values())
        if not layers:
            self._append("system", "No layers in project.")
            return
        lines = ["Layers in project:"]
        for lyr in layers:
            lines.append(
                f"  - {lyr.name()} (type: {lyr.type()}, CRS: {lyr.crs().authid()})"
            )
        self.input.setText("\n".join(lines))

    def _inject_crs(self):
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.input.setText(f"Project CRS: {crs.authid()} — {crs.description()}")

    def _inject_layer_info(self):
        layer = self.iface.activeLayer()
        if layer is None:
            self._append("system", "No active layer selected.")
            return
        try:
            info = qgis_tools.dispatch_tool(
                "get_layer_info",
                {"layer_name": layer.name(), "sample_features": 3},
            )
            self.input.setText(f"Active layer info:\n{info}")
        except Exception as exc:
            self._append("error", str(exc))

    def _inject_selected(self):
        layer = self.iface.activeLayer()
        if layer is None:
            self._append("system", "No active layer selected.")
            return
        try:
            info = qgis_tools.dispatch_tool(
                "get_selected_features", {"layer_name": layer.name()}
            )
            self.input.setText(f"Selected features:\n{info}")
        except Exception as exc:
            self._append("error", str(exc))

    def _inject_extent(self):
        try:
            info = qgis_tools.dispatch_tool("get_map_extent", {})
            self.input.setText(f"Map extent:\n{info}")
        except Exception as exc:
            self._append("error", str(exc))

    def _clear(self):
        self.chat.clear()
        self.client.reset()
        self._welcome()

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    def apply_api_key(self, api_key: str):
        self.client = ClaudeClient(api_key)
        self.chat.clear()
        self._welcome()

    def _change_api_key(self):
        api_key = self.plugin.configure_api_key()
        if not api_key:
            return
        self.apply_api_key(api_key)
        self._append("system", "API key updated.")

    # ------------------------------------------------------------------
    # Sending messages & worker signals
    # ------------------------------------------------------------------

    def _send(self):
        message = self.input.text().strip()
        if not message or (self.worker and self.worker.isRunning()):
            return
        self.input.clear()
        self.send_btn.setEnabled(False)
        self.status.setText("Thinking…")
        self._append("user", message)

        self.worker = Worker(self.client, message)
        self.worker.finished.connect(self._on_reply)
        self.worker.error.connect(self._on_error)
        self.worker.tool_called.connect(self._on_tool_call)
        self.worker.start()

    def _on_reply(self, reply: str):
        if reply:
            self._append("assistant", reply)
        self.send_btn.setEnabled(True)
        self.status.setText("")

    def _on_error(self, err: str):
        self._append("error", err)
        self.send_btn.setEnabled(True)
        self.status.setText("")

    def _on_tool_call(self, tool_name: str, tool_input_json: str):
        try:
            tool_input = json.loads(tool_input_json)
        except Exception:
            tool_input = tool_input_json

        if isinstance(tool_input, dict):
            params = ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
        else:
            params = str(tool_input)

        self._append("tool", f"{tool_name}({params})")


# ---------------------------------------------------------------------------
# Plugin entry-point
# ---------------------------------------------------------------------------

class AIAssistantPlugin:
    SETTINGS_API_KEY = "qgis_ai_assistant/api_key"

    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        # Bind the QGIS interface to the tools module so it can load layers etc.
        qgis_tools.initialize(self.iface)

        self.action = QAction("AI GIS Agent", self.iface.mainWindow())
        self.action.setToolTip("Open AI GIS Agent panel")
        self.action.triggered.connect(self.toggle_panel)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("AI GIS Agent", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("AI GIS Agent", self.action)
        if self.dock:
            self.dock.deleteLater()
            self.dock = None

    def toggle_panel(self):
        if self.dock and self.dock.isVisible():
            self.dock.hide()
            return

        api_key = self._ensure_api_key()
        if not api_key:
            return

        if self.dock is None:
            panel = AIPanel(self, api_key)
            self.dock = QDockWidget("AI GIS Agent", self.iface.mainWindow())
            self.dock.setObjectName("AIGISAgentDock")
            self.dock.setWidget(panel)
            self.dock.setMinimumWidth(380)
            self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)
        else:
            self.dock.widget().apply_api_key(api_key)

        self.dock.show()

    # ------------------------------------------------------------------
    # API key helpers
    # ------------------------------------------------------------------

    def _ensure_api_key(self) -> str:
        key = QSettings().value(self.SETTINGS_API_KEY, "")
        if not key:
            key = self._prompt_api_key()
            if not key:
                return ""
            QSettings().setValue(self.SETTINGS_API_KEY, key)
        return key

    def configure_api_key(self) -> str:
        existing = QSettings().value(self.SETTINGS_API_KEY, "")
        key = self._prompt_api_key(existing)
        if not key:
            return ""
        QSettings().setValue(self.SETTINGS_API_KEY, key)
        return key

    def _prompt_api_key(self, existing: str = "") -> str:
        key, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Anthropic API Key",
            "Enter your Anthropic API key\n(stored in QGIS settings):",
            QLineEdit.Password,
            existing,
        )
        if not ok or not key.strip():
            return ""
        return key.strip()
