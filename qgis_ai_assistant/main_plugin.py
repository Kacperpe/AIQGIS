from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtWidgets import QAction, QDockWidget

from .assistant_dock import AssistantDockWidget
from .claude_client import AIClient
from .settings_dialog import SettingsDialog


class AIAssistantPlugin:
    SETTINGS_PROVIDER_KEY = "qgis_ai_assistant/provider"
    SETTINGS_PROVIDER_CONFIG_PREFIX = "qgis_ai_assistant/provider_config"
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

        config = self.ensure_provider_configuration()
        if not config:
            return

        provider, provider_settings = config
        if self.dock is None:
            content = AssistantDockWidget(self, provider, provider_settings)
            self.dock = QDockWidget("AI Assistant", self.iface.mainWindow())
            self.dock.setObjectName("AIAssistantDock")
            self.dock.setWidget(content)
            self.dock.setMinimumWidth(350)
            self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)
        else:
            self.dock.widget().apply_credentials(provider, provider_settings)

        self.dock.show()
        self.dock.raise_()

    def ensure_provider_configuration(self):
        provider = self._get_provider()
        if provider:
            saved_settings = self._get_saved_provider_settings(provider)
            try:
                provider_settings = AIClient.normalize_settings(provider, saved_settings)
            except ValueError:
                provider_settings = None
            if provider_settings and not AIClient.provider_configuration_needed(provider, saved_settings):
                return provider, provider_settings

        return self.open_settings_dialog(provider or "lmstudio")

    def configure_provider(self):
        return self.open_settings_dialog(self._get_provider() or "lmstudio")

    def configure_provider_settings(self):
        return self.open_settings_dialog(self._get_provider() or "lmstudio")

    def open_settings_dialog(self, provider):
        dialog = SettingsDialog(
            self.iface.mainWindow(),
            provider,
            self._get_saved_provider_settings,
        )
        if dialog.exec_() != SettingsDialog.Accepted:
            return None

        selected_provider = dialog.selected_provider
        selected_settings = dialog.selected_settings
        self._save_provider(selected_provider)
        self._save_provider_settings(selected_provider, selected_settings)
        return selected_provider, selected_settings

    def _get_provider(self):
        provider = str(QSettings().value(self.SETTINGS_PROVIDER_KEY, "") or "").strip()
        if provider not in AIClient.provider_ids():
            return ""
        return provider

    def _save_provider(self, provider):
        QSettings().setValue(self.SETTINGS_PROVIDER_KEY, provider)

    def _provider_setting_key(self, provider, field_id):
        return f"{self.SETTINGS_PROVIDER_CONFIG_PREFIX}/{provider}/{field_id}"

    def _get_saved_provider_settings(self, provider):
        settings = {}
        qsettings = QSettings()
        for field in AIClient.provider_setting_fields(provider):
            field_id = field["id"]
            value = qsettings.value(self._provider_setting_key(provider, field_id), None)
            if value is None and field_id == "api_key":
                value = qsettings.value(f"{self.SETTINGS_API_KEY_PREFIX}/{provider}", "")
            settings[field_id] = "" if value is None else str(value)
        return settings

    def _save_provider_settings(self, provider, settings):
        normalized = AIClient.normalize_settings(provider, settings)
        qsettings = QSettings()
        for field in AIClient.provider_setting_fields(provider):
            field_id = field["id"]
            value = normalized.get(field_id, "")
            qsettings.setValue(self._provider_setting_key(provider, field_id), value)
            if field_id == "api_key":
                qsettings.setValue(f"{self.SETTINGS_API_KEY_PREFIX}/{provider}", value)
        return normalized
