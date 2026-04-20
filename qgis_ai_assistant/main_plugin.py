import html

from qgis.PyQt.QtCore import QSettings, QThread, Qt, pyqtSignal
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget
)

from .claude_client import AIClient


def html_escape_code(text):
    code = text.strip("\n")
    if "\n" in code:
        first_line, rest = code.split("\n", 1)
        if first_line.isidentifier():
            code = rest
    return html.escape(code)


class Worker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client, message):
        super().__init__()
        self.client = client
        self.message = message

    def run(self):
        try:
            reply = self.client.chat(self.message)
            self.finished.emit(reply)
        except Exception as exc:
            self.error.emit(str(exc))


class AIPanel(QWidget):
    def __init__(self, plugin, provider, api_key):
        super().__init__()
        self.plugin = plugin
        self.iface = plugin.iface
        self.provider = provider
        self.client = AIClient(provider, api_key)
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
            "QTextEdit { background:#1e1e1e; color:#d4d4d4; "
            "font-family: Consolas, monospace; font-size:12px; }"
        )
        root.addWidget(self.chat)

        btn_row = QHBoxLayout()
        for label, slot in [
            ("Provider", self._change_provider),
            ("API Key", self._change_api_key),
            ("Warstwy", self._inject_layers),
            ("CRS", self._inject_crs),
            ("Wyczysc", self._clear),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        send_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Zadaj pytanie o dane GIS...")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Wyslij")
        self.send_btn.setFixedWidth(90)
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.input)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

        self.status = QLabel("")
        self.status.setStyleSheet("color: gray; font-size: 10px;")
        root.addWidget(self.status)

    def _welcome(self):
        provider_name = AIClient.provider_label(self.provider)
        self._append(
            "system",
            f"AI Assistant gotowy. Provider: {provider_name}. Kliknij Warstwy, aby dodac kontekst projektu.",
        )

    def _append(self, role, text):
        colours = {"user": "#569cd6", "claude": "#4ec9b0", "system": "#808080", "error": "#f44747"}
        labels = {"user": "Ty", "claude": "AI", "system": "System", "error": "Blad"}
        colour = colours.get(role, "#ffffff")
        label = labels.get(role, role)
        parts = text.split("```")
        message_html = f'<span style="color:{colour};font-weight:bold">{label}:</span> '
        for index, part in enumerate(parts):
            if index % 2 == 1:
                escaped = html_escape_code(part)
                message_html += (
                    "<br><pre style=\"background:#2d2d2d;color:#ce9178;padding:6px;"
                    f"border-radius:4px;white-space:pre-wrap\">{escaped}</pre>"
                )
            else:
                message_html += html.escape(part).replace("\n", "<br>")
        self.chat.append(message_html + "<br>")
        self.chat.moveCursor(QTextCursor.End)

    def _inject_layers(self):
        layers = self.iface.mapCanvas().layers()
        if not layers:
            self._append("system", "Brak warstw w projekcie.")
            return
        info = "Warstwy w projekcie:\n"
        for lyr in layers:
            info += f"  - {lyr.name()} (typ: {lyr.type()}, CRS: {lyr.crs().authid()})\n"
        self.input.setText(info.strip())

    def _inject_crs(self):
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.input.setText(f"Aktualny CRS projektu: {crs.authid()} - {crs.description()}")

    def _clear(self):
        self.chat.clear()
        self.client.reset()
        self._welcome()

    def apply_credentials(self, provider, api_key, reset_chat=False):
        provider_changed = provider != self.provider
        self.provider = provider
        self.client = AIClient(provider, api_key)
        if reset_chat or provider_changed:
            self.chat.clear()
            self._welcome()

    def _change_provider(self):
        config = self.plugin.configure_provider()
        if not config:
            return
        provider, api_key = config
        self.apply_credentials(provider, api_key, reset_chat=True)
        self._append("system", f"Przelaczono providera na {AIClient.provider_label(provider)}.")

    def _change_api_key(self):
        config = self.plugin.configure_api_key()
        if not config:
            return
        provider, api_key = config
        self.apply_credentials(provider, api_key, reset_chat=True)
        self._append("system", f"Zaktualizowano klucz API dla {AIClient.provider_label(provider)}.")

    def _send(self):
        message = self.input.text().strip()
        if not message or (self.worker and self.worker.isRunning()):
            return
        self.input.clear()
        self.send_btn.setEnabled(False)
        provider_name = AIClient.provider_label(self.provider)
        self.status.setText(f"Czekam na odpowiedz z {provider_name}...")
        self._append("user", message)
        self.worker = Worker(self.client, message)
        self.worker.finished.connect(self._on_reply)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_reply(self, reply):
        self._append("claude", reply)
        self.send_btn.setEnabled(True)
        self.status.setText("")

    def _on_error(self, err):
        self._append("error", err)
        self.send_btn.setEnabled(True)
        self.status.setText("")


class AIAssistantPlugin:
    SETTINGS_PROVIDER_KEY = "qgis_ai_assistant/provider"
    SETTINGS_API_KEY_PREFIX = "qgis_ai_assistant/api_key"

    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        self.action = QAction("AI Assistant", self.iface.mainWindow())
        self.action.setToolTip("Otworz panel AI Assistant")
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
        config = self.ensure_credentials()
        if not config:
            return
        provider, api_key = config
        if self.dock is None:
            panel = AIPanel(self, provider, api_key)
            self.dock = QDockWidget("AI Assistant", self.iface.mainWindow())
            self.dock.setObjectName("AIAssistantDock")
            self.dock.setWidget(panel)
            self.dock.setMinimumWidth(350)
            self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)
        else:
            self.dock.widget().apply_credentials(provider, api_key)
        self.dock.show()

    def ensure_credentials(self):
        provider = self._get_provider()
        api_key = self._get_saved_api_key(provider)
        if not api_key:
            api_key = self._prompt_api_key(provider)
            if not api_key:
                return None
            self._save_api_key(provider, api_key)
        return provider, api_key

    def configure_provider(self):
        current_provider = self._get_provider()
        provider = self._prompt_provider(current_provider)
        if not provider:
            return None
        self._save_provider(provider)
        api_key = self._get_saved_api_key(provider)
        if not api_key:
            api_key = self._prompt_api_key(provider)
            if not api_key:
                self._save_provider(current_provider)
                return None
            self._save_api_key(provider, api_key)
        return provider, api_key

    def configure_api_key(self):
        provider = self._get_provider()
        existing_key = self._get_saved_api_key(provider)
        api_key = self._prompt_api_key(provider, existing_key)
        if not api_key:
            return None
        self._save_api_key(provider, api_key)
        return provider, api_key

    def _get_provider(self):
        provider = QSettings().value(self.SETTINGS_PROVIDER_KEY, "anthropic")
        if provider not in AIClient.provider_ids():
            return "anthropic"
        return provider

    def _save_provider(self, provider):
        QSettings().setValue(self.SETTINGS_PROVIDER_KEY, provider)

    def _get_saved_api_key(self, provider):
        return QSettings().value(f"{self.SETTINGS_API_KEY_PREFIX}/{provider}", "")

    def _save_api_key(self, provider, api_key):
        QSettings().setValue(f"{self.SETTINGS_API_KEY_PREFIX}/{provider}", api_key)

    def _prompt_provider(self, current_provider):
        labels = AIClient.provider_labels()
        current_label = AIClient.provider_label(current_provider)
        current_index = labels.index(current_label) if current_label in labels else 0
        label, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            "Wybierz provider AI",
            "Dostepne API:",
            labels,
            current_index,
            False,
        )
        if not ok:
            return None
        return AIClient.provider_from_label(label)

    def _prompt_api_key(self, provider, existing_key=""):
        provider_label = AIClient.provider_label(provider)
        key, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            f"Klucz API: {provider_label}",
            (
                f"Wklej klucz API dla {provider_label}:\n"
                "(zostanie zapamietany w ustawieniach QGIS)"
            ),
            QLineEdit.Password,
            existing_key,
        )
        if not ok or not key.strip():
            return ""
        return key.strip()
