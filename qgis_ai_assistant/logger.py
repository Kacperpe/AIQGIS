import html
import json
import os
from datetime import datetime


class SessionLogger:
    def __init__(self, log_dir=None):
        self.log_dir = log_dir or os.path.join(os.path.expanduser("~"), "qgis_ai_logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self._start_new_session()

    def _start_new_session(self):
        now = datetime.now()
        self.session = {
            "session_id": now.strftime("%Y%m%d_%H%M%S"),
            "started_at": now.isoformat(),
            "messages": [],
            "tool_calls": [],
            "errors": [],
            "summary": {},
        }

    def reset_session(self):
        self._start_new_session()

    def log_user_message(self, text):
        self.session["messages"].append(
            {
                "role": "user",
                "text": str(text or ""),
                "timestamp": datetime.now().isoformat(),
            }
        )

    def log_agent_reply(self, text):
        self.session["messages"].append(
            {
                "role": "agent",
                "text": str(text or ""),
                "timestamp": datetime.now().isoformat(),
            }
        )

    def log_tool_call(self, tool_name, tool_input, result, success):
        result_text = self._stringify(result)
        self.session["tool_calls"].append(
            {
                "tool": str(tool_name or ""),
                "input": tool_input if isinstance(tool_input, dict) else {"value": tool_input},
                "result_preview": result_text[:300],
                "success": bool(success),
                "timestamp": datetime.now().isoformat(),
            }
        )
        if not success:
            self.session["errors"].append(
                {
                    "tool": str(tool_name or ""),
                    "error": result_text,
                    "timestamp": datetime.now().isoformat(),
                }
            )

    def finish_session(self):
        tools_used = [tool["tool"] for tool in self.session["tool_calls"]]
        tools_ok = [tool["tool"] for tool in self.session["tool_calls"] if tool["success"]]
        tools_failed = [tool["tool"] for tool in self.session["tool_calls"] if not tool["success"]]

        self.session["summary"] = {
            "ended_at": datetime.now().isoformat(),
            "total_messages": len(self.session["messages"]),
            "total_tool_calls": len(tools_used),
            "successful_tools": tools_ok,
            "failed_tools": tools_failed,
            "unique_tools_used": sorted(set(tools_used)),
            "error_count": len(self.session["errors"]),
        }

        json_path = os.path.join(self.log_dir, f"session_{self.session['session_id']}.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(self.session, handle, ensure_ascii=False, indent=2)

        html_path = self._generate_html_report()
        return html_path

    def _generate_html_report(self):
        session = self.session
        summary = session["summary"]

        tools_ok_html = "".join(
            f'<span class="badge ok">{html.escape(tool)}</span>'
            for tool in summary.get("successful_tools", [])
        )
        tools_fail_html = "".join(
            f'<span class="badge fail">{html.escape(tool)}</span>'
            for tool in summary.get("failed_tools", [])
        )
        unique_html = "".join(
            f'<span class="badge neutral">{html.escape(tool)}</span>'
            for tool in summary.get("unique_tools_used", [])
        )

        messages_html = ""
        for message in session["messages"]:
            role_class = "user" if message["role"] == "user" else "agent"
            messages_html += f"""
            <div class="msg {role_class}">
                <span class="msg-role">{html.escape(message['role'].upper())}</span>
                <span class="msg-time">{html.escape(message['timestamp'][11:19])}</span>
                <div class="msg-text">{html.escape(message['text'])}</div>
            </div>"""

        tool_rows = ""
        for tool in session["tool_calls"]:
            status = "OK" if tool["success"] else "ERR"
            params = html.escape(self._stringify(tool["input"]))
            preview = html.escape(tool["result_preview"])
            tool_rows += f"""
            <tr class="{'row-ok' if tool['success'] else 'row-fail'}">
                <td>{status}</td>
                <td><code>{html.escape(tool['tool'])}</code></td>
                <td><small>{params}</small></td>
                <td><small>{preview}</small></td>
                <td>{html.escape(tool['timestamp'][11:19])}</td>
            </tr>"""

        errors_html = ""
        for error in session["errors"]:
            errors_html += f"""
            <div class="error-box">
                <strong>{html.escape(error['tool'])}</strong> @ {html.escape(error['timestamp'][11:19])}<br>
                <code>{html.escape(error['error'])}</code>
            </div>"""

        html_report = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Raport sesji - {html.escape(session['session_id'])}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; margin: 0; padding: 30px; }}
  h1 {{ color: #00d4ff; font-size: 22px; margin-bottom: 4px; }}
  h2 {{ color: #94a3b8; font-size: 14px; border-bottom: 1px solid #1e2d40; padding-bottom: 8px; margin: 24px 0 12px; }}
  .meta {{ color: #64748b; font-size: 12px; font-family: monospace; margin-bottom: 24px; }}
  .stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .stat {{ background: #111827; border: 1px solid #1e2d40; border-radius: 8px; padding: 14px 20px; min-width: 120px; }}
  .stat .val {{ font-size: 28px; font-weight: 800; color: #00d4ff; }}
  .stat .lbl {{ font-size: 11px; color: #64748b; margin-top: 2px; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-family: monospace; margin: 2px; }}
  .badge.ok {{ background: #0a1a14; border: 1px solid #10b981; color: #10b981; }}
  .badge.fail {{ background: #1a0a0a; border: 1px solid #f44747; color: #f44747; }}
  .badge.neutral {{ background: #111827; border: 1px solid #334155; color: #94a3b8; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; padding: 8px; background: #111827; color: #64748b; font-weight: 600; }}
  td {{ padding: 7px 8px; border-bottom: 1px solid #1e2d40; vertical-align: top; }}
  .row-ok {{ background: rgba(16,185,129,.03); }}
  .row-fail {{ background: rgba(244,71,71,.05); }}
  .msg {{ padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; }}
  .msg.user {{ background: #0d1a2a; border-left: 3px solid #00d4ff; }}
  .msg.agent {{ background: #0a1a14; border-left: 3px solid #10b981; }}
  .msg-role {{ font-size: 10px; font-weight: 700; letter-spacing: 2px; margin-right: 8px; }}
  .msg-time {{ font-size: 10px; color: #64748b; font-family: monospace; }}
  .msg-text {{ margin-top: 6px; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }}
  .error-box {{ background: #1a0a0a; border: 1px solid #f44747; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px; font-size: 12px; }}
  code {{ font-family: 'Courier New', monospace; }}
</style>
</head>
<body>
<h1>QGIS AI Agent - Raport sesji</h1>
<div class="meta">ID: {html.escape(session['session_id'])} | Start: {html.escape(session['started_at'][:19])} | Koniec: {html.escape(summary.get('ended_at', '')[:19])}</div>

<div class="stats">
  <div class="stat"><div class="val">{summary.get('total_messages', 0)}</div><div class="lbl">Wiadomosci</div></div>
  <div class="stat"><div class="val">{summary.get('total_tool_calls', 0)}</div><div class="lbl">Wywolan narzedzi</div></div>
  <div class="stat"><div class="val" style="color:#10b981">{len(summary.get('successful_tools', []))}</div><div class="lbl">Sukces</div></div>
  <div class="stat"><div class="val" style="color:#f44747">{summary.get('error_count', 0)}</div><div class="lbl">Bledy</div></div>
</div>

<h2>Narzedzia uzyte w sesji</h2>
{unique_html or '<span style="color:#64748b">brak</span>'}

<h2>Sukces / Bledy</h2>
{tools_ok_html}
{tools_fail_html or '<span style="color:#64748b">brak bledow</span>'}

<h2>Log wywolan narzedzi</h2>
<table>
  <tr><th>Status</th><th>Narzedzie</th><th>Parametry</th><th>Wynik (podglad)</th><th>Czas</th></tr>
  {tool_rows or '<tr><td colspan="5" style="color:#64748b">brak wywolan</td></tr>'}
</table>

{'<h2>Bledy</h2>' + errors_html if session['errors'] else ''}

<h2>Historia rozmowy</h2>
{messages_html}

</body></html>"""

        html_path = os.path.join(self.log_dir, f"report_{session['session_id']}.html")
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(html_report)
        return html_path

    def _stringify(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)
