import json
import urllib.error
import urllib.parse
import urllib.request


class AIClient:
    PROVIDERS = {
        "anthropic": {
            "label": "Anthropic",
            "model": "claude-sonnet-4-20250514",
        },
        "openai": {
            "label": "OpenAI",
            "model": "gpt-4o-mini",
        },
        "gemini": {
            "label": "Google Gemini",
            "model": "gemini-2.5-flash",
        },
        "openrouter": {
            "label": "OpenRouter",
            "model": "openai/gpt-4o-mini",
        },
        "mistral": {
            "label": "Mistral AI",
            "model": "mistral-large-latest",
        },
        "xai": {
            "label": "xAI",
            "model": "grok-4.20-reasoning",
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

    def __init__(self, provider: str, api_key: str):
        self.history = []
        self.system_prompt = (
            "Jestes ekspertem GIS zintegrowanym z QGIS 3.x. "
            "Specjalizujesz sie w analizie danych przestrzennych, "
            "pisaniu kodu PyQGIS, ukladach wspolrzednych (CRS/EPSG), "
            "oraz bibliotekach GeoPandas, Shapely i GDAL. "
            "Gdy piszesz kod PyQGIS, uzywaj iface i QgsProject.instance(), "
            "dodawaj obsluge bledow i komentuj kod po polsku. "
            "Odpowiadaj po polsku, konkretnie i technicznie."
        )
        self.set_credentials(provider, api_key)

    def set_credentials(self, provider: str, api_key: str):
        if provider not in self.PROVIDERS:
            raise ValueError(f"Nieobslugiwany provider API: {provider}")
        self.provider = provider
        self.api_key = api_key.strip()
        self.model = self.PROVIDERS[provider]["model"]

    def chat(self, user_message: str) -> str:
        pending_history = self.history + [{"role": "user", "content": user_message}]
        payload, headers, url = self._build_request(pending_history)
        result = self._post_json(url, payload, headers)
        reply = self._parse_reply(result)
        if not reply:
            raise Exception("API zwrocilo pusta odpowiedz.")
        self.history = pending_history + [{"role": "assistant", "content": reply}]
        return reply

    def reset(self):
        self.history = []

    def _build_request(self, history):
        if self.provider == "anthropic":
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

        if self.provider == "gemini":
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
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
        elif self.provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers["HTTP-Referer"] = "https://github.com/Kacperpe/AIQGIS"
            headers["X-Title"] = "AI Assistant for QGIS"
        elif self.provider == "mistral":
            url = "https://api.mistral.ai/v1/chat/completions"
        elif self.provider == "xai":
            url = "https://api.x.ai/v1/chat/completions"
        else:
            raise Exception(f"Brak konfiguracji URL dla providera: {self.provider}")
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
        if self.provider == "anthropic":
            parts = data.get("content", [])
            texts = [
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(text for text in texts if text).strip()

        if self.provider == "gemini":
            candidates = data.get("candidates", [])
            if not candidates:
                feedback = data.get("promptFeedback", {})
                reason = feedback.get("blockReason") or "Brak kandydatow w odpowiedzi."
                raise Exception(f"Gemini nie zwrocilo odpowiedzi: {reason}")
            parts = candidates[0].get("content", {}).get("parts", [])
            texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
            return "\n".join(text for text in texts if text).strip()

        choices = data.get("choices", [])
        if not choices:
            raise Exception("Provider nie zwrocil listy choices.")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(text for text in texts if text).strip()
        return str(content).strip()

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
