"""
action_card_widget.py
---------------------
Karta akcji pokazywana gdy AI proponuje wykonanie kodu lub operacji.
Zawiera trzy przyciski zgody + opcje pomocnicze.

Sygnały:
  approve_once_clicked(signature: str)        – Approve once
  approve_session_clicked(signature: str)     – Approve for this command in session
  allow_all_clicked()                         – Always allow everything
  insert_console_clicked(code: str)           – Wstaw do konsoli
  copy_code_clicked(code: str)               – Kopiuj kod
  cancel_clicked()                            – Anuluj
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
)


_RISK_COLORS = {
    "low": "#4ec9b0",
    "medium": "#d7ba7d",
    "high": "#f44747",
}

_CARD_STYLE = """
QFrame#actionCard {
    background: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
    padding: 4px;
}
QLabel#cardTitle {
    color: #ffffff;
    font-weight: bold;
    font-size: 12px;
}
QLabel#cardSummary {
    color: #cccccc;
    font-size: 11px;
}
QLabel#cardRisk {
    font-size: 10px;
    font-weight: bold;
}
QTextEdit#codePreview {
    background: #1e1e1e;
    color: #ce9178;
    font-family: Consolas, monospace;
    font-size: 11px;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
}
QPushButton#btnPrimary {
    background: #0e639c;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: bold;
}
QPushButton#btnPrimary:hover { background: #1177bb; }
QPushButton#btnSecondary {
    background: #3c3c3c;
    color: #cccccc;
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 11px;
}
QPushButton#btnSecondary:hover { background: #505050; }
QPushButton#btnDanger {
    background: #5a1d1d;
    color: #f48771;
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 11px;
}
QPushButton#btnDanger:hover { background: #6e2020; }
QPushButton#btnGhost {
    background: transparent;
    color: #808080;
    border: none;
    padding: 5px 8px;
    font-size: 10px;
}
QPushButton#btnGhost:hover { color: #cccccc; }
"""


class ActionCardWidget(QFrame):
    approve_once_clicked = pyqtSignal(str)
    approve_session_clicked = pyqtSignal(str)
    allow_all_clicked = pyqtSignal()
    insert_console_clicked = pyqtSignal(str)
    copy_code_clicked = pyqtSignal(str)
    cancel_clicked = pyqtSignal()

    def __init__(self, proposal, parent=None):
        super().__init__(parent)
        self.proposal = proposal
        self.setObjectName("actionCard")
        self.setStyleSheet(_CARD_STYLE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Nagłówek: tytuł + badge ryzyka
        header = QHBoxLayout()
        title = QLabel(self.proposal.title or "Proponowana akcja")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch()

        risk_color = _RISK_COLORS.get(self.proposal.risk_level, "#808080")
        risk_label = QLabel(f"Ryzyko: {self.proposal.risk_level}")
        risk_label.setObjectName("cardRisk")
        risk_label.setStyleSheet(f"color: {risk_color};")
        header.addWidget(risk_label)
        layout.addLayout(header)

        # Opis
        if self.proposal.summary:
            summary = QLabel(self.proposal.summary)
            summary.setObjectName("cardSummary")
            summary.setWordWrap(True)
            layout.addWidget(summary)

        # Podgląd kodu (zwijany, max 150 px)
        if self.proposal.code:
            code_view = QTextEdit()
            code_view.setObjectName("codePreview")
            code_view.setReadOnly(True)
            code_view.setPlainText(self.proposal.code)
            code_view.setMaximumHeight(150)
            layout.addWidget(code_view)

        # --- Przyciski zgody (główna rząd) ---
        approval_row = QHBoxLayout()
        approval_row.setSpacing(6)

        btn_once = QPushButton("✔ Approve once")
        btn_once.setObjectName("btnPrimary")
        btn_once.setToolTip("Pozwól wykonać tylko tę jedną akcję")
        btn_once.clicked.connect(
            lambda: self.approve_once_clicked.emit(self.proposal.operation_signature)
        )
        approval_row.addWidget(btn_once)

        btn_session = QPushButton("↩ Approve for this command in session")
        btn_session.setObjectName("btnSecondary")
        btn_session.setToolTip(
            "Zapamiętaj zgodę dla tej samej operacji na tych samych danych w bieżącej sesji"
        )
        btn_session.clicked.connect(
            lambda: self.approve_session_clicked.emit(self.proposal.operation_signature)
        )
        approval_row.addWidget(btn_session)

        btn_all = QPushButton("⚡ Always allow everything")
        btn_all.setObjectName("btnDanger")
        btn_all.setToolTip("Wykonuj wszystkie akcje automatycznie bez pytania (ostrożnie!)")
        btn_all.clicked.connect(self.allow_all_clicked.emit)
        approval_row.addWidget(btn_all)

        layout.addLayout(approval_row)

        # --- Przyciski pomocnicze (drugi rząd) ---
        tools_row = QHBoxLayout()
        tools_row.setSpacing(4)

        if self.proposal.code:
            btn_insert = QPushButton("📋 Wstaw do konsoli")
            btn_insert.setObjectName("btnGhost")
            btn_insert.clicked.connect(
                lambda: self.insert_console_clicked.emit(self.proposal.code)
            )
            tools_row.addWidget(btn_insert)

            btn_copy = QPushButton("⎘ Kopiuj kod")
            btn_copy.setObjectName("btnGhost")
            btn_copy.clicked.connect(
                lambda: self.copy_code_clicked.emit(self.proposal.code)
            )
            tools_row.addWidget(btn_copy)

        tools_row.addStretch()

        btn_cancel = QPushButton("✕ Anuluj")
        btn_cancel.setObjectName("btnGhost")
        btn_cancel.clicked.connect(self.cancel_clicked.emit)
        tools_row.addWidget(btn_cancel)

        layout.addLayout(tools_row)
