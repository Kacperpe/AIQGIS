import html
import re

from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


ASSISTANT_STYLESHEET = """
QWidget#assistantRoot {
    background: #15181e;
    color: #f3f4f6;
}
QFrame#chatHeader {
    background: #1b1f27;
    border: 1px solid #262b35;
    border-radius: 16px;
}
QLabel#headerTitle {
    color: #f8fafc;
    font-size: 16px;
    font-weight: 600;
}
QLabel#headerSubtitle {
    color: #8d96a6;
    font-size: 11px;
}
QToolButton#headerButton,
QToolButton#bubbleAction,
QToolButton#codeAction,
QToolButton#plusButton,
QToolButton#sendButton {
    background: transparent;
    border: none;
    border-radius: 12px;
    color: #c7ceda;
    padding: 6px 10px;
}
QToolButton#headerButton:hover,
QToolButton#bubbleAction:hover,
QToolButton#codeAction:hover,
QToolButton#plusButton:hover {
    background: #252a34;
    color: #f8fafc;
}
QToolButton#sendButton {
    background: #3f6ed8;
    color: #f8fafc;
    font-weight: 600;
    padding: 8px 14px;
}
QToolButton#sendButton:hover {
    background: #4e7ce5;
}
QToolButton#sendButton:disabled {
    background: #263247;
    color: #73819a;
}
QFrame#welcomeCard {
    background: #1a1f27;
    border: 1px solid #262c36;
    border-radius: 22px;
}
QLabel#welcomeEyebrow {
    color: #7aa2ff;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
QLabel#welcomeTitle {
    color: #f8fafc;
    font-size: 24px;
    font-weight: 600;
}
QLabel#welcomeBody {
    color: #98a2b3;
    font-size: 13px;
    line-height: 1.5em;
}
QPushButton#suggestionChip {
    background: #202630;
    border: 1px solid #2a3140;
    border-radius: 16px;
    color: #e5e7eb;
    padding: 10px 14px;
    text-align: left;
}
QPushButton#suggestionChip:hover {
    background: #2a3140;
    border-color: #3a465c;
}
QFrame#contextBar {
    background: #171b22;
    border: 1px solid #232a34;
    border-radius: 14px;
}
QFrame#contextChip {
    background: #1f242d;
    border: 1px solid #2a313d;
    border-radius: 12px;
}
QLabel#contextTitle {
    color: #8a94a6;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
}
QLabel#contextValue {
    color: #f4f6fb;
    font-size: 12px;
    font-weight: 500;
}
QLabel#assistantStatus {
    color: #7f8898;
    font-size: 11px;
    padding-left: 4px;
}
QFrame#chatComposer {
    background: #1b2028;
    border: 1px solid #27303c;
    border-radius: 18px;
}
QTextEdit#composerInput {
    background: transparent;
    border: none;
    color: #f3f4f6;
    padding: 6px 2px;
    font-size: 13px;
}
QTextEdit#composerInput:focus {
    border: none;
}
QFrame#messageBubble {
    border-radius: 18px;
    border: 1px solid transparent;
}
QFrame#messageBubble[bubbleRole="assistant"] {
    background: #1d222b;
    border-color: #2a313c;
}
QFrame#messageBubble[bubbleRole="user"] {
    background: #274362;
    border-color: #32557d;
}
QFrame#messageBubble[bubbleRole="system"] {
    background: #1b2430;
    border-color: #2b3848;
}
QFrame#messageBubble[bubbleRole="error"] {
    background: #362026;
    border-color: #5b2f38;
}
QLabel#bubbleRoleLabel {
    color: #94a3b8;
    font-size: 11px;
    font-weight: 600;
}
QLabel#userMessageLabel {
    color: #f8fafc;
    font-size: 13px;
    line-height: 1.45em;
}
QTextBrowser#markdownBlock {
    background: transparent;
    border: none;
    color: #e5e7eb;
    font-size: 13px;
}
QFrame#codeBlock {
    background: #11151b;
    border: 1px solid #2d3642;
    border-radius: 14px;
}
QLabel#codeLanguage {
    color: #98a2b3;
    font-size: 11px;
    font-weight: 600;
}
QPlainTextEdit#codeEditor {
    background: transparent;
    border: none;
    color: #d8dee9;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
    selection-background-color: #2d4e7c;
}
QScrollArea#chatScrollArea {
    border: none;
    background: transparent;
}
"""


CODE_BLOCK_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)


def split_message_segments(text):
    source = text or ""
    segments = []
    last_index = 0
    for match in CODE_BLOCK_RE.finditer(source):
        before = source[last_index:match.start()]
        if before.strip():
            segments.append({"type": "markdown", "text": before})
        segments.append(
            {
                "type": "code",
                "language": match.group(1).strip(),
                "code": match.group(2).rstrip("\n"),
            }
        )
        last_index = match.end()

    tail = source[last_index:]
    if tail.strip() or not segments:
        segments.append({"type": "markdown", "text": tail})
    return segments


def extract_code_blocks(text):
    blocks = []
    for match in CODE_BLOCK_RE.finditer(text or ""):
        blocks.append(match.group(2).rstrip("\n"))
    return blocks


def format_inline_markdown(text):
    parts = re.split(r"(`[^`]+`)", text)
    rendered = []
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            code = html.escape(part[1:-1])
            rendered.append(
                "<code style=\"background:#12161d;border:1px solid #29313d;"
                "border-radius:6px;padding:2px 5px;color:#dbeafe;\">"
                f"{code}</code>"
            )
            continue
        escaped = html.escape(part)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
        rendered.append(escaped)
    return "".join(rendered)


def markdown_to_html(text):
    lines = (text or "").replace("\r\n", "\n").split("\n")
    parts = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            title = format_inline_markdown(heading_match.group(2))
            size = {1: 20, 2: 17, 3: 15}[level]
            parts.append(
                f"<h{level} style=\"margin:10px 0 6px;color:#f8fafc;font-size:{size}px;\">"
                f"{title}</h{level}>"
            )
            index += 1
            continue

        bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        ordered_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if bullet_match or ordered_match:
            ordered = bool(ordered_match)
            items = []
            while index < len(lines):
                current = lines[index].strip()
                current_match = (
                    re.match(r"^\d+\.\s+(.+)$", current)
                    if ordered
                    else re.match(r"^[-*+]\s+(.+)$", current)
                )
                if not current_match:
                    break
                items.append(f"<li>{format_inline_markdown(current_match.group(1))}</li>")
                index += 1
            tag = "ol" if ordered else "ul"
            marker_margin = "20px" if ordered else "18px"
            parts.append(
                f"<{tag} style=\"margin:6px 0 12px {marker_margin};color:#e5e7eb;\">"
                f"{''.join(items)}</{tag}>"
            )
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines):
            current = lines[index].strip()
            if not current:
                break
            if re.match(r"^(#{1,3})\s+(.+)$", current):
                break
            if re.match(r"^[-*+]\s+(.+)$", current):
                break
            if re.match(r"^\d+\.\s+(.+)$", current):
                break
            paragraph.append(current)
            index += 1
        parts.append(
            "<p style=\"margin:0 0 12px;color:#dbe2ea;line-height:1.6em;\">"
            f"{format_inline_markdown(' '.join(paragraph))}</p>"
        )
    return "".join(parts) or "<p style=\"margin:0;color:#dbe2ea;\"></p>"


class MarkdownTextView(QTextBrowser):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("markdownBlock")
        self.setFrameShape(QFrame.NoFrame)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setHtml(markdown_to_html(text))
        self._refresh_height()

    def _refresh_height(self):
        document_height = self.document().documentLayout().documentSize().height()
        self.setFixedHeight(int(document_height + 6))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refresh_height)


class CodeBlockWidget(QFrame):
    def __init__(self, code, language="", parent=None):
        super().__init__(parent)
        self.code = code or ""
        self.language = language or "Kod"
        self.setObjectName("codeBlock")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        language_label = QLabel(self.language)
        language_label.setObjectName("codeLanguage")
        top_row.addWidget(language_label)
        top_row.addStretch(1)

        copy_button = QToolButton()
        copy_button.setObjectName("codeAction")
        copy_button.setText("Kopiuj kod")
        copy_button.clicked.connect(self._copy_code)
        top_row.addWidget(copy_button)
        root.addLayout(top_row)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("codeEditor")
        self.editor.setReadOnly(True)
        self.editor.setPlainText(self.code)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        line_count = max(3, min(12, self.code.count("\n") + 1))
        self.editor.setFixedHeight(28 + (line_count * 18))
        root.addWidget(self.editor)

    def _copy_code(self):
        QApplication.clipboard().setText(self.code)


class MessageBubble(QWidget):
    def __init__(self, role, text, parent=None):
        super().__init__(parent)
        self.role = role
        self.text = text or ""
        self.code_blocks = extract_code_blocks(self.text)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.bubble = QFrame()
        self.bubble.setObjectName("messageBubble")
        self.bubble.setProperty("bubbleRole", role)
        self.bubble.setMaximumWidth(620)
        self.bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(14, 12, 14, 12)
        bubble_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        role_label = QLabel(self._role_label())
        role_label.setObjectName("bubbleRoleLabel")
        top_row.addWidget(role_label)
        top_row.addStretch(1)

        if role != "user":
            copy_button = QToolButton()
            copy_button.setObjectName("bubbleAction")
            copy_button.setText("Kopiuj")
            copy_button.clicked.connect(self._copy_message)
            top_row.addWidget(copy_button)

            if self.code_blocks:
                copy_code_button = QToolButton()
                copy_code_button.setObjectName("bubbleAction")
                copy_code_button.setText("Kopiuj kod")
                copy_code_button.clicked.connect(self._copy_all_code)
                top_row.addWidget(copy_code_button)

        bubble_layout.addLayout(top_row)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        if role == "user":
            label = QLabel(html.escape(self.text).replace("\n", "<br>"))
            label.setObjectName("userMessageLabel")
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content_layout.addWidget(label)
        else:
            for segment in split_message_segments(self.text):
                if segment["type"] == "markdown":
                    if not segment["text"].strip() and self.code_blocks:
                        continue
                    content_layout.addWidget(MarkdownTextView(segment["text"]))
                else:
                    content_layout.addWidget(
                        CodeBlockWidget(segment["code"], segment["language"] or "Kod")
                    )
        bubble_layout.addWidget(content)

        if role == "user":
            root.addStretch(1)
            root.addWidget(self.bubble)
        else:
            root.addWidget(self.bubble)
            root.addStretch(1)

    def _role_label(self):
        return {
            "user": "Ty",
            "assistant": "AI Assistant",
            "system": "System",
            "error": "Blad",
        }.get(self.role, self.role)

    def _copy_message(self):
        QApplication.clipboard().setText(self.text)

    def _copy_all_code(self):
        QApplication.clipboard().setText("\n\n".join(self.code_blocks))


class ChatView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("chatScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(12)
        self.container_layout.addStretch(1)

        self.scroll_area.setWidget(self.container)
        root.addWidget(self.scroll_area)

    def add_message(self, role, text):
        bubble = MessageBubble(role, text)
        self.messages.append({"role": role, "text": text})
        self.container_layout.insertWidget(self.container_layout.count() - 1, bubble)
        QTimer.singleShot(0, self.scroll_to_bottom)

    def clear_messages(self):
        self.messages = []
        while self.container_layout.count() > 1:
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        QTimer.singleShot(0, self.scroll_to_top)

    def scroll_to_top(self):
        self.scroll_area.verticalScrollBar().setValue(0)

    def scroll_to_bottom(self):
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def transcript_text(self):
        lines = []
        for message in self.messages:
            label = {
                "user": "Ty",
                "assistant": "AI Assistant",
                "system": "System",
                "error": "Blad",
            }.get(message["role"], message["role"])
            lines.append(f"{label}:\n{message['text']}")
        return "\n\n".join(lines)

    def has_messages(self):
        return bool(self.messages)


class WelcomeView(QWidget):
    suggestionTriggered = pyqtSignal(str)

    SUGGESTIONS = [
        ("Analiza CRS", "Przeanalizuj aktualny CRS projektu i podpowiedz, czy jest odpowiedni do tej pracy."),
        ("Pomoc z PyQGIS", "Pomoz mi przygotowac rozwiazanie w PyQGIS dla aktualnego zadania."),
        ("Utworz skrypt", "Utworz skrypt PyQGIS dla aktywnej warstwy i opisz kolejne kroki."),
        ("Wyjasnij blad", "Wyjasnij blad w moim workflow GIS i zaproponuj konkretna poprawke."),
        ("Pracuj na aktywnej warstwie", "Pracuj na aktywnej warstwie i zaproponuj sensowna analize."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addStretch(1)

        card = QFrame()
        card.setObjectName("welcomeCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 22)
        card_layout.setSpacing(16)

        eyebrow = QLabel("AI ASSISTANT")
        eyebrow.setObjectName("welcomeEyebrow")
        card_layout.addWidget(eyebrow)

        title = QLabel("Jak moge pomoc w pracy z danymi GIS?")
        title.setObjectName("welcomeTitle")
        title.setWordWrap(True)
        card_layout.addWidget(title)

        body = QLabel(
            "Wybierz sugestie na start albo wpisz wlasne pytanie. "
            "Interfejs zachowuje sie jak nowoczesny czat, ale korzysta z kontekstu QGIS."
        )
        body.setObjectName("welcomeBody")
        body.setWordWrap(True)
        card_layout.addWidget(body)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, (label, prompt) in enumerate(self.SUGGESTIONS):
            button = QPushButton(label)
            button.setObjectName("suggestionChip")
            button.clicked.connect(lambda _checked=False, value=prompt: self.suggestionTriggered.emit(value))
            row = index // 2
            column = index % 2
            grid.addWidget(button, row, column)
        card_layout.addLayout(grid)

        root.addWidget(card)
        root.addStretch(1)


class ComposerTextEdit(QTextEdit):
    sendRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("composerInput")
        self.setAcceptRichText(False)
        self.setPlaceholderText("Zadaj pytanie o dane GIS...")
        self.setTabChangesFocus(False)
        self.textChanged.connect(self._adjust_height)
        self._adjust_height()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.sendRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _adjust_height(self):
        doc_height = self.document().documentLayout().documentSize().height()
        height = max(44, min(140, int(doc_height + 16)))
        self.setFixedHeight(height)


class ChatComposer(QFrame):
    sendRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatComposer")

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.plus_button = QToolButton()
        self.plus_button.setObjectName("plusButton")
        self.plus_button.setText("+")
        self.plus_button.setPopupMode(QToolButton.InstantPopup)
        root.addWidget(self.plus_button, 0, Qt.AlignBottom)

        self.input = ComposerTextEdit()
        self.input.sendRequested.connect(self._emit_send)
        root.addWidget(self.input, 1)

        self.send_button = QToolButton()
        self.send_button.setObjectName("sendButton")
        self.send_button.setText("Wyslij")
        self.send_button.clicked.connect(self._emit_send)
        root.addWidget(self.send_button, 0, Qt.AlignBottom)

    def set_plus_menu(self, menu):
        self.plus_button.setMenu(menu)

    def set_busy(self, busy):
        self.send_button.setDisabled(busy)
        self.plus_button.setDisabled(busy)
        self.input.setDisabled(busy)

    def text(self):
        return self.input.toPlainText()

    def set_text(self, text):
        self.input.setPlainText(text or "")
        self.input.moveCursor(QTextCursor.End)
        self.input._adjust_height()

    def focus_input(self):
        self.input.setFocus(Qt.OtherFocusReason)

    def clear(self):
        self.input.clear()
        self.input._adjust_height()

    def _emit_send(self):
        self.sendRequested.emit(self.text())


class ChatHeader(QFrame):
    settingsRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatHeader")

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(2)

        title = QLabel("AI Assistant")
        title.setObjectName("headerTitle")
        title_wrap.addWidget(title)

        self.subtitle = QLabel("Nowoczesny asystent GIS dla QGIS")
        self.subtitle.setObjectName("headerSubtitle")
        title_wrap.addWidget(self.subtitle)
        root.addLayout(title_wrap, 1)

        self.history_button = QToolButton()
        self.history_button.setObjectName("headerButton")
        self.history_button.setText("Historia")
        self.history_button.setPopupMode(QToolButton.InstantPopup)
        root.addWidget(self.history_button)

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("headerButton")
        self.settings_button.setText("Ustawienia")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        root.addWidget(self.settings_button)

        self.more_button = QToolButton()
        self.more_button.setObjectName("headerButton")
        self.more_button.setText("...")
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        root.addWidget(self.more_button)

    def set_history_menu(self, menu):
        self.history_button.setMenu(menu)

    def set_more_menu(self, menu):
        self.more_button.setMenu(menu)

    def update_session(self, provider_label, model_label, tools_enabled):
        tools_label = "toole QGIS aktywne" if tools_enabled else "tryb czatu"
        self.subtitle.setText(f"{provider_label} · {model_label} · {tools_label}")


class GISContextBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contextBar")

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.layer_value = self._add_chip(root, "Warstwa")
        self.crs_value = self._add_chip(root, "CRS")
        self.selected_value = self._add_chip(root, "Zaznaczone")

    def _add_chip(self, layout, title):
        chip = QFrame()
        chip.setObjectName("contextChip")
        chip_layout = QVBoxLayout(chip)
        chip_layout.setContentsMargins(10, 8, 10, 8)
        chip_layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("contextTitle")
        chip_layout.addWidget(title_label)

        value_label = QLabel("-")
        value_label.setObjectName("contextValue")
        value_label.setWordWrap(True)
        chip_layout.addWidget(value_label)

        layout.addWidget(chip, 1)
        return value_label

    def set_context(self, layer_name, crs_authid, selected_count):
        self.layer_value.setText(layer_name or "Brak aktywnej warstwy")
        self.crs_value.setText(crs_authid or "-")
        self.selected_value.setText(str(selected_count if selected_count is not None else 0))
