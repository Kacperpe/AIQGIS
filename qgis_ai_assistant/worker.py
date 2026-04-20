"""Background worker thread for non-blocking AI requests.

The Worker runs client.chat() on a QThread so the Qt main thread (and therefore
the QGIS UI) stays responsive.  Tool-call notifications are forwarded to the UI
via the tool_called signal so they can be displayed as they happen.
"""

import json

from qgis.PyQt.QtCore import QThread, pyqtSignal


class Worker(QThread):
    """Executes ClaudeClient.chat() in a background thread.

    Signals
    -------
    finished(str)
        Emitted with the final assistant reply when the agentic loop ends.
    error(str)
        Emitted with a human-readable error message if an exception is raised.
    tool_called(str, str)
        Emitted each time the agent invokes a tool, before its result is sent
        back to the model.  Arguments are the tool name and the tool input
        serialised as a JSON string.
    """

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    tool_called = pyqtSignal(str, str)  # (tool_name, json_input)

    def __init__(self, client, message: str):
        super().__init__()
        self.client = client
        self.message = message

    def run(self):
        def on_tool_call(tool_name: str, tool_input: dict):
            try:
                input_str = json.dumps(tool_input, ensure_ascii=False)
            except Exception as exc:
                input_str = f"<serialization error: {exc}>"
            self.tool_called.emit(tool_name, input_str)

        try:
            reply = self.client.chat(self.message, on_tool_call=on_tool_call)
            self.finished.emit(reply or "")
        except Exception as exc:
            self.error.emit(str(exc))
