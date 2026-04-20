import urllib.request
import urllib.error
import json


class ClaudeClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "claude-sonnet-4-20250514"
        self.history = []
        self.system_prompt = (
            "Jesteś ekspertem GIS zintegrowanym z QGIS 3.x. "
            "Specjalizujesz się w analizie danych przestrzennych, "
            "pisaniu kodu PyQGIS, układach współrzędnych (CRS/EPSG), "
            "oraz bibliotekach GeoPandas, Shapely i GDAL. "
            "Gdy piszesz kod PyQGIS, używaj iface i QgsProject.instance(), "
            "dodawaj obsługę błędów i komentuj kod po polsku. "
            "Odpowiadaj po polsku, konkretnie i technicznie."
        )

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        payload = json.dumps({
            "model": self.model,
            "max_tokens": 1024,
            "system": self.system_prompt,
            "messages": self.history,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read())
            reply = result["content"][0]["text"]
            self.history.append({"role": "assistant", "content": reply})
            return reply
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            error_data = json.loads(body)
            raise Exception(f"Blad API ({e.code}): {error_data.get('error', {}).get('message', body)}")
        except Exception as e:
            raise Exception(f"Blad polaczenia: {str(e)}")

    def reset(self):
        self.history = []
