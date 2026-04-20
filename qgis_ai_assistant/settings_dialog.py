from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .claude_client import AIClient


class SettingsDialog(QDialog):
    def __init__(self, parent, provider, load_settings_callback):
        super().__init__(parent)
        self.load_settings_callback = load_settings_callback
        self.field_widgets = {}
        self.selected_provider = None
        self.selected_settings = None

        self.setWindowTitle("Ustawienia AI Assistant")
        self.setModal(True)
        self.resize(420, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Skonfiguruj sesje AI")
        title.setStyleSheet("color:#f8fafc;font-size:16px;font-weight:600;")
        root.addWidget(title)

        subtitle = QLabel(
            "Wybierz providera, model i pola potrzebne do polaczenia. "
            "Ustawienia zostana zapisane w QGIS."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#98a2b3;font-size:12px;line-height:1.5em;")
        root.addWidget(subtitle)

        self.provider_combo = QComboBox()
        self.provider_combo.setStyleSheet(
            "QComboBox { background:#1b2028; border:1px solid #2a3340; "
            "border-radius:10px; color:#f3f4f6; padding:8px; }"
        )
        for provider_id in AIClient.provider_ids():
            self.provider_combo.addItem(AIClient.provider_label(provider_id), provider_id)
        self.provider_combo.currentIndexChanged.connect(self._rebuild_fields)
        root.addWidget(self.provider_combo)

        self.fields_container = QWidget()
        self.fields_layout = QFormLayout(self.fields_container)
        self.fields_layout.setContentsMargins(0, 0, 0, 0)
        self.fields_layout.setSpacing(10)
        root.addWidget(self.fields_container)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#fca5a5;font-size:11px;")
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet(
            "QPushButton { background:#1d2430; border:1px solid #2f3947; "
            "border-radius:10px; color:#f3f4f6; padding:8px 14px; } "
            "QPushButton:hover { background:#283140; } "
            "QPushButton[text='Save'] { background:#3f6ed8; border-color:#3f6ed8; } "
            "QPushButton[text='Save']:hover { background:#4f7ee5; }"
        )
        root.addWidget(buttons)

        self.setStyleSheet("QDialog { background:#15181e; } QLabel { color:#f3f4f6; }")
        self._set_provider(provider or "lmstudio")

    def _set_provider(self, provider):
        index = self.provider_combo.findData(provider)
        if index < 0:
            index = self.provider_combo.findData("lmstudio")
        self.provider_combo.setCurrentIndex(index)
        self._rebuild_fields()

    def _clear_fields(self):
        while self.fields_layout.rowCount():
            self.fields_layout.removeRow(0)
        self.field_widgets = {}

    def _rebuild_fields(self):
        self._clear_fields()
        provider = self.provider_combo.currentData()
        saved_settings = self.load_settings_callback(provider)

        for field in AIClient.provider_setting_fields(provider):
            label = QLabel(field["label"])
            label.setStyleSheet("color:#c7ceda;font-size:12px;")

            widget = QLineEdit()
            widget.setPlaceholderText(field.get("default", ""))
            widget.setText(saved_settings.get(field["id"], "") or field.get("default", ""))
            widget.setEchoMode(QLineEdit.Password if field.get("secret") else QLineEdit.Normal)
            widget.setStyleSheet(
                "QLineEdit { background:#1b2028; border:1px solid #2a3340; "
                "border-radius:10px; color:#f3f4f6; padding:8px; } "
                "QLineEdit:focus { border-color:#4f7ee5; }"
            )
            widget.setToolTip(field["prompt"])
            self.field_widgets[field["id"]] = widget
            self.fields_layout.addRow(label, widget)

    def get_configuration(self):
        provider = self.provider_combo.currentData()
        settings = {}
        for field in AIClient.provider_setting_fields(provider):
            value = self.field_widgets[field["id"]].text().strip()
            if not value:
                value = str(field.get("default", "")).strip()
            if field["id"] == "base_url":
                value = value.rstrip("/")
            settings[field["id"]] = value
        return provider, AIClient.normalize_settings(provider, settings)

    def accept(self):
        try:
            provider, settings = self.get_configuration()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return

        self.selected_provider = provider
        self.selected_settings = settings
        self.error_label.hide()
        super().accept()
