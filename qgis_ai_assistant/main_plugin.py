from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QAction,
    QInputDialog, QLineEdit as QLE, QLabel
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QSettings
from qgis.PyQt.QtGui import QTextCursor
from .claude_client import ClaudeClient


# ── Background worker thread (keeps UI responsive) ────────────────────────────

class Worker(QThread):
    finished    = pyqtSignal(str)
    error       = pyqtSignal(str)
    tool_called = pyqtSignal(str, dict)

    def __init__(self, client, message):
        super().__init__()
        self.client  = client
        self.message = message

    def run(self):
        try:
            reply = self.client.chat(
                self.message,
                on_tool_call=lambda name, inp: self.tool_called.emit(name, inp)
            )
            self.finished.emit(reply)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Side panel UI ─────────────────────────────────────────────────────────────

class AIPanel(QWidget):
    def __init__(self, iface, api_key):
        super().__init__()
        self.iface  = iface
        self.client = ClaudeClient(api_key)
        self.worker = None
        self._build_ui()
        self._welcome()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setStyleSheet(
            "QTextEdit { background:#1e1e1e; color:#d4d4d4;"
            "font-family: Consolas, monospace; font-size:12px; }"
        )
        root.addWidget(self.chat)

        btn_row = QHBoxLayout()
        for label, slot in [
            ("Warstwy", self._inject_layers),
            ("CRS",     self._inject_crs),
            ("Wyczysc", self._clear),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        send_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Powiedz agentowi co ma zrobic...")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Wyslij")
        self.send_btn.setFixedWidth(90)
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.input)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#808080; font-size:10px;")
        root.addWidget(self.status)

    def _welcome(self):
        self._append("system",
            "Agent GIS gotowy. Przyklady:\n"
            "  - 'Zrob bufor 500m na warstwie drogi'\n"
            "  - 'Pokaz atrybuty zaznaczonych obiektow'\n"
            "  - 'Wczytaj plik C:/dane/granice.shp'\n"
            "  - 'Ile obiektow ma warstwa budynki?'"
        )

    def _append(self, role, text):
        colours = {
            "user":   "#569cd6",
            "claude": "#4ec9b0",
            "system": "#808080",
            "error":  "#f44747",
            "tool":   "#c586c0",
        }
        labels = {
            "user":   "Ty",
            "claude": "Agent",
            "system": "System",
            "error":  "Blad",
            "tool":   "Narzedzie",
        }
        colour = colours.get(role, "#ffffff")
        label  = labels.get(role, role)
        parts  = text.split("```")
        html   = f'<span style="color:{colour};font-weight:bold">{label}:</span> '
        for i, part in enumerate(parts):
            if i % 2 == 1:
                escaped = part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html += (
                    f'<br><pre style="background:#2d2d2d;color:#ce9178;'
                    f'padding:6px;border-radius:4px;white-space:pre-wrap">{escaped}</pre>'
                )
            else:
                html += part.replace("\n", "<br>")
        self.chat.append(html + "<br>")
        self.chat.moveCursor(QTextCursor.End)

    def _inject_layers(self):
        from qgis.core import QgsProject
        layers = QgsProject.instance().mapLayers().values()
        if not layers:
            self._append("system", "Brak warstw w projekcie.")
            return
        info = "Warstwy w projekcie:\n"
        for lyr in layers:
            info += f"  - {lyr.name()} (CRS: {lyr.crs().authid()})\n"
        self.input.setText(info.strip())

    def _inject_crs(self):
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.input.setText(f"Aktualny CRS: {crs.authid()} - {crs.description()}")

    def _clear(self):
        self.chat.clear()
        self.client.reset()
        self._welcome()

    def _on_tool_called(self, tool_name: str, tool_input: dict):
        params_str = ", ".join(f"{k}={v}" for k, v in tool_input.items())
        self._append("tool", f"wywoluje: {tool_name}({params_str})")
        self.status.setText(f"Agent: {tool_name}...")

    def _send(self):
        message = self.input.text().strip()
        if not message or (self.worker and self.worker.isRunning()):
            return
        self.input.clear()
        self.send_btn.setEnabled(False)
        self.status.setText("Agent mysli...")
        self._append("user", message)

        self.worker = Worker(self.client, message)
        self.worker.finished.connect(self._on_reply)
        self.worker.error.connect(self._on_error)
        self.worker.tool_called.connect(self._on_tool_called)
        self.worker.start()

    def _on_reply(self, reply):
        if reply:
            self._append("claude", reply)
        self.send_btn.setEnabled(True)
        self.status.setText("")

    def _on_error(self, err):
        self._append("error", err)
        self.send_btn.setEnabled(True)
        self.status.setText("")


# ── Main plugin class ─────────────────────────────────────────────────────────

class AIAssistantPlugin:
    SETTINGS_KEY = "qgis_ai_assistant/api_key"

    def __init__(self, iface):
        self.iface  = iface
        self.dock   = None
        self.action = None

    def initGui(self):
        self.action = QAction("AI Assistant", self.iface.mainWindow())
        self.action.setToolTip("Otworz panel AI Agent GIS")
        self.action.triggered.connect(self.toggle_panel)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("AI Assistant", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("AI Assistant", self.action)
        if self.dock:
            self.dock.deleteLater()
            self.dock = None

    def toggle_panel(self):
        if self.dock and self.dock.isVisible():
            self.dock.hide()
            return
        api_key = self._get_api_key()
        if not api_key:
            return
        if self.dock is None:
            panel     = AIPanel(self.iface, api_key)
            self.dock = QDockWidget("AI Agent GIS", self.iface.mainWindow())
            self.dock.setObjectName("AIAssistantDock")
            self.dock.setWidget(panel)
            self.dock.setMinimumWidth(380)
            self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()

    def _get_api_key(self):
        settings = QSettings()
        key = settings.value(self.SETTINGS_KEY, "")
        if not key:
            key, ok = QInputDialog.getText(
                self.iface.mainWindow(),
                "Klucz Anthropic API",
                "Wklej swoj klucz API (sk-ant-...):\n(zostanie zapamietany w QGIS)",
                QLE.Password,
            )
            if not ok or not key.strip():
                return ""
            key = key.strip()
            settings.setValue(self.SETTINGS_KEY, key)
        return key
