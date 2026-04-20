import urllib.request
import urllib.error
import json
from .qgis_tools import TOOL_DEFINITIONS, dispatch_tool


class ClaudeClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "claude-sonnet-4-20250514"
        self.history = []
        self.system_prompt = (
            "Jesteś agentem GIS zintegrowanym z QGIS 3.x. "
            "Masz dostęp do narzędzi które pozwalają Ci działać bezpośrednio w QGIS. "
            "Gdy użytkownik prosi o zadanie:\n"
            "1. Najpierw użyj list_layers aby zobaczyć co jest w projekcie\n"
            "2. Użyj search_processing_algorithms aby znaleźć odpowiedni algorytm\n"
            "3. Użyj get_algorithm_info aby poznać parametry\n"
            "4. Wykonaj zadanie używając dostępnych narzędzi\n"
            "5. Poinformuj użytkownika co zostało zrobione\n\n"
            "Odpowiadaj po polsku. Gdy wykonujesz wiele kroków, informuj o każdym z nich."
        )

    def _call_api(self, messages: list) -> dict:
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 4096,
            "system": self.system_prompt,
            "tools": TOOL_DEFINITIONS,
            "messages": messages,
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
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8"))
            raise Exception(f"Błąd API ({e.code}): {body.get('error', {}).get('message', str(body))}")

    def chat(self, user_message: str, on_tool_call=None) -> str:
        """
        Pętla agentowa: wysyła wiadomość, obsługuje tool_use w pętli
        aż Claude skończy i zwróci stop_reason == 'end_turn'.
        on_tool_call(tool_name, tool_input) – callback do UI (pokazuje co agent robi)
        """
        self.history.append({"role": "user", "content": user_message})
        messages = list(self.history)

        while True:
            response = self._call_api(messages)
            stop_reason = response.get("stop_reason")
            content     = response.get("content", [])

            # Zbierz tekst i wywołania narzędzi z odpowiedzi
            text_parts = []
            tool_calls = []

            for block in content:
                if block["type"] == "text":
                    text_parts.append(block["text"])
                elif block["type"] == "tool_use":
                    tool_calls.append(block)

            # Dodaj odpowiedź asystenta do historii wiadomości
            messages.append({"role": "assistant", "content": content})

            if stop_reason == "end_turn" or not tool_calls:
                # Agent skończył – zapisz do historii i zwróć tekst
                final_text = "\n".join(text_parts)
                self.history.append({"role": "assistant", "content": content})
                return final_text

            # Agent chce wywołać narzędzia – wykonaj je i odeślij wyniki
            tool_results = []
            for tool_call in tool_calls:
                tool_name  = tool_call["name"]
                tool_input = tool_call["input"]
                tool_use_id = tool_call["id"]

                if on_tool_call:
                    on_tool_call(tool_name, tool_input)

                try:
                    result_str = dispatch_tool(tool_name, tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result_str
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"BŁĄD: {str(e)}",
                        "is_error": True
                    })

            messages.append({"role": "user", "content": tool_results})

    def reset(self):
        self.history = []
