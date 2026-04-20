import json
import urllib.error
import urllib.parse
import urllib.request


class AIClient:
    PROVIDERS = {
        "anthropic": {
            "label": "Anthropic",
            "model": "claude-sonnet-4-20250514",
            "api_style": "anthropic",
            "settings": [
                {
                    "id": "api_key",
                    "label": "Klucz API",
                    "prompt": "Wklej klucz API dla Anthropic:",
                    "secret": True,
                    "required": True,
                    "prompt_if_missing": True,
                }
            ],
        },
        "openai": {
            "label": "OpenAI",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_style": "openai_compatible",
            "settings": [
                {
                    "id": "api_key",
                    "label": "Klucz API",
                    "prompt": "Wklej klucz API dla OpenAI:",
                    "secret": True,
                    "required": True,
                    "prompt_if_missing": True,
                }
            ],
        },
        "gemini": {
            "label": "Google Gemini",
            "model": "gemini-2.5-flash",
            "api_style": "gemini",
            "settings": [
                {
                    "id": "api_key",
                    "label": "Klucz API",
                    "prompt": "Wklej klucz API dla Google Gemini:",
                    "secret": True,
                    "required": True,
                    "prompt_if_missing": True,
                }
            ],
        },
        "openrouter": {
            "label": "OpenRouter",
            "model": "openai/gpt-4o-mini",
            "base_url": "https://openrouter.ai/api/v1",
            "api_style": "openai_compatible",
            "settings": [
                {
                    "id": "api_key",
                    "label": "Klucz API",
                    "prompt": "Wklej klucz API dla OpenRouter:",
                    "secret": True,
                    "required": True,
                    "prompt_if_missing": True,
                }
            ],
        },
        "mistral": {
            "label": "Mistral AI",
            "model": "mistral-large-latest",
            "base_url": "https://api.mistral.ai/v1",
            "api_style": "openai_compatible",
            "settings": [
                {
                    "id": "api_key",
                    "label": "Klucz API",
                    "prompt": "Wklej klucz API dla Mistral AI:",
                    "secret": True,
                    "required": True,
                    "prompt_if_missing": True,
                }
            ],
        },
        "xai": {
            "label": "xAI",
            "model": "grok-4.20-reasoning",
            "base_url": "https://api.x.ai/v1",
            "api_style": "openai_compatible",
            "settings": [
                {
                    "id": "api_key",
                    "label": "Klucz API",
                    "prompt": "Wklej klucz API dla xAI:",
                    "secret": True,
                    "required": True,
                    "prompt_if_missing": True,
                }
            ],
        },
        "lmstudio": {
            "label": "LM Studio",
            "model": "local-model",
            "base_url": "http://127.0.0.1:1234/v1",
            "api_style": "openai_compatible",
            "settings": [
                {
                    "id": "base_url",
                    "label": "Endpoint URL",
                    "prompt": (
                        "Podaj adres serwera LM Studio "
                        "(OpenAI-compatible, zwykle http://127.0.0.1:1234/v1):"
                    ),
                    "required": True,
                    "default": "http://127.0.0.1:1234/v1",
                    "prompt_if_missing": True,
                },
                {
                    "id": "model",
                    "label": "Model",
                    "prompt": (
                        "Podaj model dla LM Studio "
                        "(np. local-model albo identyfikator zaladowanego modelu):"
                    ),
                    "required": True,
                    "default": "local-model",
                    "prompt_if_missing": True,
                },
                {
                    "id": "api_key",
                    "label": "Klucz API (opcjonalny)",
                    "prompt": (
                        "Jesli lokalny serwer LM Studio wymaga autoryzacji, "
                        "wklej klucz API. Mozesz zostawic puste."
                    ),
                    "secret": True,
                    "required": False,
                    "default": "",
                },
            ],
        },
    }

    @classmethod
    def provider_ids(cls):
        return list(cls.PROVIDERS.keys())

    @classmethod
    def provider_labels(cls):
        return [config["label"] for config in cls.PROVIDERS.values()]

    @classmethod
    def provider_label(cls, provider):
        config = cls.PROVIDERS.get(provider, {})
        return config.get("label", provider)

    @classmethod
    def provider_from_label(cls, label):
        for provider, config in cls.PROVIDERS.items():
            if config["label"] == label:
                return provider
        return None

    @classmethod
    def provider_setting_fields(cls, provider):
        config = cls.PROVIDERS.get(provider, {})
        return [dict(field) for field in config.get("settings", [])]

    @classmethod
    def provider_configuration_needed(cls, provider, saved_settings):
        settings = saved_settings or {}
        for field in cls.provider_setting_fields(provider):
            if field.get("prompt_if_missing") and not str(settings.get(field["id"], "")).strip():
                return True
        return False

    @classmethod
    def normalize_settings(cls, provider, settings):
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Nieobslugiwany provider API: {provider}")

        config = cls.PROVIDERS[provider]
        source = settings or {}
        normalized = {}

        for field in cls.provider_setting_fields(provider):
            field_id = field["id"]
            value = source.get(field_id, field.get("default", ""))
            value = "" if value is None else str(value).strip()
            if not value:
                value = str(field.get("default", "")).strip()
            if field_id == "base_url":
                value = value.rstrip("/")
            if field.get("required") and not value:
                raise ValueError(
                    f"Brak wymaganego pola '{field['label']}' dla providera "
                    f"{cls.provider_label(provider)}."
                )
            normalized[field_id] = value

        if "api_key" not in normalized:
            normalized["api_key"] = ""
        if "model" not in normalized:
            normalized["model"] = config.get("model", "")
        if "base_url" not in normalized and config.get("base_url"):
            normalized["base_url"] = str(config["base_url"]).rstrip("/")
        return normalized

    def __init__(self, provider: str, settings):
        self.history = []
        self.system_prompt = (
            "Jestes ekspertem GIS zintegrowanym z QGIS 3.x. "
            "Specjalizujesz sie w analizie danych przestrzennych, "
            "pisaniu kodu PyQGIS, ukladach wspolrzednych (CRS/EPSG), "
            "oraz bibliotekach GeoPandas, Shapely i GDAL. "
            "Masz dostep do narzedzi QGIS i gdy pytanie dotyczy aktualnego projektu, "
            "warstw, CRS, selekcji, tabel atrybutow, stanu projektu albo operacji GIS, "
            "najpierw uzywaj narzedzi zamiast zgadywac. "
            "Dla ogolnego kontekstu projektu uzywaj get_project_info, dla aktywnej warstwy "
            "get_active_layer_info, a dla selekcji get_selected_features_info. "
            "Przed operacjami modyfikujacymi dane, warstwy lub projekt najpierw "
            "uzyj preview_action, a dopiero potem wykonuj zmiane, chyba ze uzytkownik "
            "wprost kaze od razu wykonac operacje. "
            "Gdy piszesz kod PyQGIS, uzywaj iface i QgsProject.instance(), "
            "dodawaj obsluge bledow i komentuj kod po polsku. "
            "Odpowiadaj po polsku, konkretnie i technicznie."
        )
        self.set_credentials(provider, settings)

    def set_credentials(self, provider: str, settings):
        config = self.PROVIDERS.get(provider)
        if not config:
            raise ValueError(f"Nieobslugiwany provider API: {provider}")

        normalized = self.normalize_settings(provider, settings)
        self.provider = provider
        self.settings = normalized
        self.api_style = config.get("api_style", "openai_compatible")
        self.api_key = normalized.get("api_key", "")
        self.model = normalized.get("model", config.get("model", ""))
        self.base_url = normalized.get("base_url", "").rstrip("/")

    def supports_tools(self):
        return self.api_style == "openai_compatible"

    def chat(self, user_message: str, tools=None, tool_executor=None, status_callback=None) -> str:
        pending_history = self.history + [{"role": "user", "content": user_message}]

        if self.supports_tools() and tools and tool_executor:
            reply, updated_history = self._chat_with_tools(
                pending_history,
                tools,
                tool_executor,
                status_callback=status_callback,
            )
        else:
            payload, headers, url = self._build_request(pending_history)
            result = self._post_json(url, payload, headers)
            reply = self._parse_reply(result)
            updated_history = pending_history + [{"role": "assistant", "content": reply}]

        if not reply:
            raise Exception("API zwrocilo pusta odpowiedz.")
        self.history = updated_history
        return reply

    def reset(self):
        self.history = []

    def _chat_with_tools(self, pending_history, tools, tool_executor, status_callback=None):
        history = list(pending_history)

        for _ in range(20):
            payload, headers, url = self._build_request(history, tools=tools)
            result = self._post_json(url, payload, headers)
            message = self._extract_openai_message(result)
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                history.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                )
                for tool_call in tool_calls:
                    tool_name = tool_call.get("function", {}).get("name", "")
                    tool_args = self._parse_tool_arguments(tool_call)
                    if status_callback:
                        status_callback(f"Wywoluje narzedzie QGIS: {tool_name}...")
                    tool_result = tool_executor(tool_name, tool_args)
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", ""),
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )
                if status_callback:
                    status_callback("Oczekuje na odpowiedz modelu po wykonaniu narzedzi...")
                continue

            reply = self._openai_content_to_text(message.get("content", ""))
            if not reply and isinstance(message.get("refusal"), str):
                reply = message["refusal"].strip()
            if not reply:
                raise Exception("Model nie zwrocil tresci odpowiedzi koncowej.")
            history.append({"role": "assistant", "content": reply})
            return reply, history

        raise Exception("Przekroczono limit krokow narzedzi w jednej odpowiedzi.")

    def _build_request(self, history, tools=None):
        if self.api_style == "anthropic":
            payload = {
                "model": self.model,
                "max_tokens": 1024,
                "system": self.system_prompt,
                "messages": history,
            }
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            return payload, headers, "https://api.anthropic.com/v1/messages"

        if self.api_style == "gemini":
            payload = {
                "systemInstruction": {"parts": [{"text": self.system_prompt}]},
                "contents": self._gemini_contents(history),
                "generationConfig": {"maxOutputTokens": 1024},
            }
            key = urllib.parse.quote(self.api_key, safe="")
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{self.model}:generateContent?key={key}"
            )
            headers = {"Content-Type": "application/json"}
            return payload, headers, url

        payload = {
            "model": self.model,
            "messages": self._openai_messages(history),
            "max_tokens": 1024,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if not self.base_url:
            raise Exception(f"Brak konfiguracji URL dla providera: {self.provider}")

        url = f"{self.base_url}/chat/completions"
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/Kacperpe/AIQGIS"
            headers["X-Title"] = "AI Assistant for QGIS"
        return payload, headers, url

    def _post_json(self, url, payload, headers):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = self._extract_error_message(body)
            raise Exception(f"Blad API ({exc.code}): {message}")
        except urllib.error.URLError as exc:
            raise Exception(f"Blad polaczenia: {exc.reason}")
        except Exception as exc:
            raise Exception(f"Blad polaczenia: {exc}")

        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise Exception("API zwrocilo odpowiedz, ale nie w formacie JSON.")

    def _extract_error_message(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body.strip() or "Nieznany blad."

        error = data.get("error")
        if isinstance(error, dict):
            return error.get("message") or json.dumps(error, ensure_ascii=False)
        if isinstance(error, str):
            return error
        if isinstance(data.get("message"), str):
            return data["message"]
        if isinstance(data.get("detail"), str):
            return data["detail"]
        return json.dumps(data, ensure_ascii=False)

    def _parse_reply(self, data):
        if self.api_style == "anthropic":
            parts = data.get("content", [])
            texts = [
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(text for text in texts if text).strip()

        if self.api_style == "gemini":
            candidates = data.get("candidates", [])
            if not candidates:
                feedback = data.get("promptFeedback", {})
                reason = feedback.get("blockReason") or "Brak kandydatow w odpowiedzi."
                raise Exception(f"Gemini nie zwrocilo odpowiedzi: {reason}")
            parts = candidates[0].get("content", {}).get("parts", [])
            texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
            return "\n".join(text for text in texts if text).strip()

        message = self._extract_openai_message(data)
        return self._openai_content_to_text(message.get("content", ""))

    def _extract_openai_message(self, data):
        choices = data.get("choices", [])
        if not choices:
            raise Exception("Provider nie zwrocil listy choices.")
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            raise Exception("Provider nie zwrocil poprawnego obiektu message.")
        return message

    def _openai_content_to_text(self, content):
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(text for text in texts if text).strip()
        return str(content or "").strip()

    def _parse_tool_arguments(self, tool_call):
        raw_arguments = tool_call.get("function", {}).get("arguments", "{}")
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str):
            raise Exception("Model zwrocil niepoprawny format argumentow narzedzia.")
        text = raw_arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise Exception(f"Niepoprawny JSON argumentow narzedzia: {text}") from exc
        if not isinstance(parsed, dict):
            raise Exception("Argumenty narzedzia musza byc obiektem JSON.")
        return parsed

    def _openai_messages(self, history):
        return [{"role": "system", "content": self.system_prompt}] + history

    def _gemini_contents(self, history):
        contents = []
        for message in history:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append(
                {
                    "role": role,
                    "parts": [{"text": message["content"]}],
                }
            )
        return contents


ClaudeClient = AIClient
