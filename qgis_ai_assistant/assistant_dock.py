import html
import json
import threading
import webbrowser
from pathlib import Path

from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .action_card_widget import ActionCardWidget
from .action_flow import (
    CONFIRMATION_REQUIRED_TOOLS,
    LLMResponseParser,
    PermissionStore,
    ToolExecutionGuard,
)
from .claude_client import AIClient
from .qgis_tools import QGISToolExecutor


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
    status = pyqtSignal(str)
    tool_requested = pyqtSignal(str, dict)

    def __init__(self, client, message, tools):
        super().__init__()
        self.client = client
        self.message = message
        self.tools = tools or []
        self._tool_event = threading.Event()
        self._tool_result = None

    def run(self):
        try:
            reply = self.client.chat(
                self.message,
                tools=self.tools,
                tool_executor=self._execute_tool,
                status_callback=self.status.emit,
            )
            self.finished.emit(reply)
        except Exception as exc:
            self.error.emit(str(exc))

    def _execute_tool(self, tool_name, tool_args):
        self._tool_result = None
        self._tool_event.clear()
        self.tool_requested.emit(tool_name, tool_args)
        if not self._tool_event.wait(300):
            raise Exception(f"Przekroczono czas oczekiwania na narzedzie: {tool_name}")
        return self._tool_result

    def set_tool_result(self, result):
        self._tool_result = result
        self._tool_event.set()


class AssistantDockWidget(QWidget):
    def __init__(self, plugin, provider, provider_settings):
        super().__init__()
        self.plugin = plugin
        self.iface = plugin.iface
        self.provider = provider
        self.provider_settings = provider_settings
        self.client = AIClient(provider, provider_settings)
        self.tool_executor = QGISToolExecutor(self.iface)
        self.worker = None

        self.permission_store = PermissionStore()
        self.response_parser = LLMResponseParser()
        self.execution_guard = ToolExecutionGuard(self.permission_store)
        self._pending_proposal = None
        self._last_tool_name = None
        self._last_tool_args = {}
        # True gdy karta akcji juz wykonala kod – blokuje ponowne wykonanie w _on_reply
        self._card_executed = False

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

        self._action_panel = QFrame()
        self._action_panel.setVisible(False)
        self._action_panel_layout = QVBoxLayout(self._action_panel)
        self._action_panel_layout.setContentsMargins(0, 4, 0, 0)
        root.addWidget(self._action_panel)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(4)
        for label, slot in [
            ("Provider", self._change_provider),
            ("Ustawienia", self._change_settings),
            ("Warstwy", self._inject_layers),
            ("CRS", self._inject_crs),
            ("Raport", self._show_report),
            ("Wyczysc", self._clear),
        ]:
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons_row.addWidget(button)
        root.addLayout(buttons_row)

        send_row = QHBoxLayout()
        send_row.setSpacing(4)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Zadaj pytanie o dane GIS...")
        self.input.returnPressed.connect(self._send)

        self.send_btn = QPushButton("Wyslij")
        self.send_btn.setFixedWidth(90)
        self.send_btn.clicked.connect(self._send)

        send_row.addWidget(self.input)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        root.addWidget(self.status_label)

    def _append(self, role, text):
        colours = {
            "user": "#569cd6",
            "assistant": "#4ec9b0",
            "system": "#808080",
            "error": "#f44747",
        }
        labels = {
            "user": "Ty",
            "assistant": "AI",
            "system": "System",
            "error": "Blad",
        }
        colour = colours.get(role, "#ffffff")
        label = labels.get(role, role)
        parts = (text or "").split("```")
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

    def _show_action_card(self, proposal):
        self._pending_proposal = proposal
        self._clear_action_panel()

        card = ActionCardWidget(proposal, self)
        card.approve_once_clicked.connect(self._on_approve_once)
        card.approve_session_clicked.connect(self._on_approve_session)
        card.allow_all_clicked.connect(self._on_allow_all)
        card.insert_console_clicked.connect(self._on_insert_console)
        card.copy_code_clicked.connect(self._on_copy_code)
        card.cancel_clicked.connect(self._on_cancel)

        self._action_panel_layout.addWidget(card)
        self._action_panel.setVisible(True)

    def _clear_action_panel(self):
        while self._action_panel_layout.count():
            item = self._action_panel_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._action_panel.setVisible(False)

    def _on_approve_once(self, signature):
        self._card_executed = True
        self._clear_action_panel()
        self._execute_proposal(self._pending_proposal)
        self._pending_proposal = None

    def _on_approve_session(self, signature):
        self._card_executed = True
        self.permission_store.approve_for_session(signature)
        self._clear_action_panel()
        self._execute_proposal(self._pending_proposal)
        self._pending_proposal = None

    def _on_allow_all(self):
        self._card_executed = True
        self.permission_store.approve_all()
        self._append("system", "Tryb automatyczny wlaczony.")
        self._clear_action_panel()
        self._execute_proposal(self._pending_proposal)
        self._pending_proposal = None

    def _on_insert_console(self, code):
        self._clear_action_panel()
        self._pending_proposal = None
        if not code:
            self._append("system", "Brak kodu do wstawienia.")
            self._finish_reply()
            return
        try:
            result = self.tool_executor.execute(
                "insert_into_pyqgis_console", {"code": code}
            )
            if isinstance(result, dict) and result.get("inserted_into_console"):
                self._append("system", "Kod wstawiony do konsoli PyQGIS.")
            else:
                detail = result.get("detail", "") if isinstance(result, dict) else ""
                msg = "Skopiowano do schowka."
                if detail:
                    msg += " " + detail
                self._append("system", msg)
        except Exception as exc:
            self._append("error", f"Blad wstawiania: {exc}")
        self._finish_reply()

    def _on_copy_code(self, code):
        QApplication.clipboard().setText(code or "")
        self._append("system", "Kod skopiowany do schowka.")

    def _on_cancel(self):
        self._clear_action_panel()
        self._pending_proposal = None
        self._append("system", "Akcja anulowana.")
        if not (self.worker and self.worker.isRunning()):
            self.send_btn.setEnabled(True)
            self.input.setFocus()

    def _execute_proposal(self, proposal):
        if not proposal:
            return

        if not proposal.code:
            self._append("assistant", proposal.summary or "Brak akcji do wykonania.")
            self._finish_reply()
            return

        try:
            result = self.tool_executor.execute(
                "run_pyqgis_code", {"code": proposal.code}
            )
        except AttributeError:
            self._on_insert_console(proposal.code)
            return
        except Exception as exc:
            self._append("error", f"Blad wykonania: {exc}")
            self._finish_reply()
            return

        if isinstance(result, dict):
            if result.get("success") or result.get("ok"):
                parts = []
                if result.get("message"):
                    parts.append(result["message"])
                stdout = result.get("stdout", "").strip()
                if stdout:
                    parts.append(stdout)
                created = result.get("created_layers", [])
                if created:
                    parts.append("Nowe warstwy: " + ", ".join(created))
                self._append("assistant", "\n\n".join(parts) or "Kod wykonano.")
            else:
                err = (
                    result.get("stderr")
                    or result.get("message")
                    or result.get("error")
                    or "Nieznany blad."
                )
                self._append("error", f"Blad wykonania:\n{err}")
        else:
            self._append("assistant", "Kod wykonano.")

        self._finish_reply()

    def _finish_reply(self):
        self.send_btn.setEnabled(True)
        self.status_label.setText("")
        self.worker = None
        self.input.setFocus()

    def _on_reply(self, raw_reply):
        # Jesli karta akcji juz wykonala kod, ignoruj kolejna propozycje z tego samego cyklu
        if self._card_executed:
            self._card_executed = False
            self._finish_reply()
            return

        proposal = self.response_parser.parse(
            model_text=raw_reply,
            last_tool_name=self._last_tool_name,
            last_tool_args=self._last_tool_args,
        )

        if proposal.response_type == "action_proposal":
            if self.execution_guard.may_execute_immediately(
                tool_name=proposal.tool_name or "pyqgis_code",
                signature=proposal.operation_signature,
            ):
                self._execute_proposal(proposal)
            else:
                self._show_action_card(proposal)
        else:
            self._append("assistant", proposal.content)
            self._finish_reply()

    def _on_error(self, err):
        self._append("error", err)
        self._finish_reply()

    def _on_status(self, text):
        self.status_label.setText(text)

    def _handle_tool_request(self, tool_name, tool_args):
        self._last_tool_name = tool_name
        self._last_tool_args = tool_args or {}
        args_text = json.dumps(tool_args, ensure_ascii=False) if tool_args else "{}"

        if tool_name in CONFIRMATION_REQUIRED_TOOLS:
            sig = self.response_parser.build_signature(
                tool_name=tool_name,
                tool_args=tool_args,
                summary=args_text,
            )
            if self.execution_guard.may_execute_immediately(tool_name, sig):
                self._append("system", f"Narzedzie QGIS (auto): {tool_name}")
                result = self.tool_executor.execute(tool_name, tool_args)
            else:
                self._append("system", f"Narzedzie QGIS (oczekuje zgody): {tool_name}")
                result = {
                    "ok": False,
                    "executed": False,
                    "deferred": True,
                    "detail": (
                        "Operacja NIE zostala wykonana. "
                        "Uzytkownik musi zatwierdzic akcje w karcie ponizej. "
                        "Poinformuj uzytkownika ze karta akcji zostala wyswietlona "
                        "i moze kliknac 'Approve once' aby potwierdzic."
                    ),
                }
            w = self.worker
            if w:
                w.set_tool_result(result)
            return

        self._append("system", f"Narzedzie QGIS: {tool_name} {args_text}")
        result = self.tool_executor.execute(tool_name, tool_args)
        w = self.worker
        if w:
            w.set_tool_result(result)

    def _send(self):
        message = self.input.text().strip()
        if not message or (self.worker and self.worker.isRunning()):
            return

        self.input.clear()
        self.send_btn.setEnabled(False)
        self._last_tool_name = None
        self._last_tool_args = {}
        self._card_executed = False
        provider_name = AIClient.provider_label(self.provider)
        self.status_label.setText(f"Czekam na odpowiedz z {provider_name}...")
        self._append("user", message)

        self.worker = Worker(
            self.client, message, self.tool_executor.definitions()
        )
        self.worker.finished.connect(self._on_reply)
        self.worker.error.connect(self._on_error)
        self.worker.status.connect(self._on_status)
        self.worker.tool_requested.connect(self._handle_tool_request)
        self.worker.start()

    def _inject_layers(self):
        layers = self.iface.mapCanvas().layers()
        if not layers:
            self._append("system", "Brak warstw w projekcie.")
            return
        info = ["Warstwy w projekcie:"]
        for layer in layers:
            info.append(
                f"  - {layer.name()} (typ: {layer.type()}, CRS: {layer.crs().authid()})"
            )
        self.input.setText("\n".join(info))

    def _inject_crs(self):
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.input.setText(
            f"Aktualny CRS projektu: {crs.authid()} - {crs.description()}"
        )

    def _clear(self):
        if self.worker and self.worker.isRunning():
            return
        self.chat.clear()
        self._clear_action_panel()
        self._pending_proposal = None
        self._card_executed = False
        self.permission_store.reset()
        self.client.reset()
        self.status_label.setText("")
        self._welcome()

    def _show_report(self):
        path = self.client.logger.finish_session()
        webbrowser.open(Path(path).resolve().as_uri())
        self._append("system", f"Raport zapisany: {path}")

    def _welcome(self):
        provider_name = AIClient.provider_label(self.provider)
        tools_state = (
            "Toole QGIS aktywne."
            if self.client.supports_tools()
            else "Toole QGIS nieaktywne dla tego providera."
        )
        self._append(
            "system",
            (
                f"AI Assistant gotowy. Provider: {provider_name}. "
                f"Model: {self.client.model}. {tools_state} "
                "Kliknij Warstwy, aby dodac kontekst projektu."
            ),
        )
        self.input.setFocus()

    def apply_credentials(self, provider, provider_settings, reset_chat=False):
        provider_changed = provider != self.provider
        self.provider = provider
        self.provider_settings = provider_settings
        self.client = AIClient(provider, provider_settings)
        if reset_chat or provider_changed:
            self.chat.clear()
            self._clear_action_panel()
            self.permission_store.reset()
            self.status_label.setText("")
            self._welcome()


    def _change_provider(self):
        if self.worker and self.worker.isRunning():
            return
        config = self.plugin.configure_provider()
        if not config:
            return
        provider, provider_settings = config
        self.apply_credentials(provider, provider_settings, reset_chat=True)
        self._append(
            "system",
            f"Przelaczono providera na {AIClient.provider_label(provider)}."
            f" Model: {self.client.model}.",
        )

    def _change_settings(self):
        if self.worker and self.worker.isRunning():
            return
        config = self.plugin.configure_provider_settings()
        if not config:
            return
        provider, provider_settings = config
        self.apply_credentials(provider, provider_settings, reset_chat=True)
        self._append(
            "system",
            f"Zaktualizowano konfiguracje dla {AIClient.provider_label(provider)}."
            f" Model: {self.client.model}.",
        )
