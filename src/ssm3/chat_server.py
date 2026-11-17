"""Local web server for the chat mode (Design Document, Chapter 9, operator console, proposal).

It serves the chat page and a small JSON interface to one ChatSession (chat.py).
It listens only on this computer (127.0.0.1), so nobody else on the network can
send orders, and it accepts orders only as JSON from its own page, so another web
page open in the same browser cannot start a model call either.

The routes:
    GET  /                    the chat page
    GET  /api/events?since=n  the events from number n on, whether an order runs, and the cell state
    POST /api/order           {"text": ..., "variant": "open" or "closed"} starts an order
    POST /api/answer          {"text": ...} answers the question the loop is waiting on
    POST /api/reset           puts the cell back in the Chapter 13 start state

Start it with scripts/chat.py. Every order uses the Groq free-tier limit.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ssm3 import planner as planner_module

HOST = "127.0.0.1"
PORT = 8765
PAGE_FILE = Path(__file__).with_name("chat_page.html")
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
MAX_BODY = 10_000


VIEWER_PAGE = Path(__file__).with_name("viewer_page.html")


def page():
    """The chat page, with the styles and the drawing of the cell taken from the replay page (viewer_page.html)."""
    viewer = VIEWER_PAGE.read_text(encoding="utf-8")
    style = viewer.split("<style>", 1)[1].split("</style>", 1)[0]
    view = viewer.split("  // CELL VIEW START", 1)[1].split("  // CELL VIEW END", 1)[0]
    chat = PAGE_FILE.read_text(encoding="utf-8")
    return chat.replace("__CELL_STYLE__", style).replace("__CELL_VIEW__", "  // CELL VIEW START" + view)


def handle(session, method, path, body=b"", content_type="", host="127.0.0.1"):
    """Answer one request. Returns (status, content type, body as bytes). Used by the server and the tests."""
    if host.split(":")[0] not in ALLOWED_HOSTS:
        return _json(403, {"ok": False, "error": "This server only answers on 127.0.0.1"})
    url = urlparse(path)
    if method == "GET" and url.path == "/":
        return 200, "text/html; charset=utf-8", page().encode("utf-8")
    if method == "GET" and url.path == "/api/events":
        try:
            since = max(0, int(parse_qs(url.query).get("since", ["0"])[0]))
        except ValueError:
            since = 0
        return _json(200, {"events": session.events_since(since), "busy": session.busy, "state": session.state(),
                           "uses_model": session.uses_model, "model": session.model})
    if method == "POST" and url.path in ("/api/order", "/api/answer", "/api/reset"):
        # Only JSON is accepted. A browser sends JSON to another site only after asking
        # that site first, and this server never says yes, so other pages cannot post here.
        if not content_type.startswith("application/json"):
            return _json(415, {"ok": False, "error": "Send JSON"})
        if len(body) > MAX_BODY:
            return _json(413, {"ok": False, "error": "Too long"})
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return _json(400, {"ok": False, "error": "Not valid JSON"})
        if not isinstance(data, dict):
            return _json(400, {"ok": False, "error": "Send a JSON object"})
        if url.path == "/api/order":
            started = session.submit(str(data.get("text", "")), str(data.get("variant", "open")))
            return _json(200 if started else 409, {"ok": started,
                                                   "error": None if started else "Empty order, or an order still runs"})
        if url.path == "/api/answer":
            text = str(data.get("text", "")).strip()
            if not text:
                return _json(400, {"ok": False, "error": "Empty answer"})
            session.answer(text)
            return _json(200, {"ok": True})
        done = session.reset()
        return _json(200 if done else 409, {"ok": done, "error": None if done else "An order still runs"})
    return _json(404, {"ok": False, "error": "Not found"})


def _json(status, payload):
    return status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8")


def make_handler(session):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, method):
            length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY + 1)
            body = self.rfile.read(length) if length else b""
            status, kind, content = handle(session, method, self.path, body, self.headers.get("Content-Type", ""),
                                           self.headers.get("Host", ""))
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            self._reply("GET")

        def do_POST(self):
            self._reply("POST")

        def log_message(self, format, *args):
            # Polling every half second would fill the terminal, so requests are not printed.
            pass

    return Handler


def serve(session, port=PORT, out=print, open_page=None):
    """Serve the session until Ctrl+C."""
    server = ThreadingHTTPServer((HOST, port), make_handler(session))
    url = f"http://{HOST}:{server.server_address[1]}/"
    out(f"Chat mode: open {url} in a browser. Stop with Ctrl+C.")
    if session.uses_model:
        out(f"Planner: {session.model} on Groq. Every order uses the Groq free-tier limit.")
        try:
            planner_module.api_key()
        except planner_module.ModelAccessError as error:
            out(f"Warning: {error}")
    if open_page:
        open_page(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        out("Chat mode stopped.")
    finally:
        server.server_close()
    return url


def main(argv=None, out=print, show=None, run=serve):
    import argparse
    import webbrowser

    from ssm3.chat import ChatSession

    parser = argparse.ArgumentParser(description="Chat mode: type kit orders for the simulated cell in a browser")
    parser.add_argument("--port", type=int, default=PORT, help=f"port on 127.0.0.1 ({PORT} by default)")
    parser.add_argument("--model", help="model ID, by default the one in planner.DEFAULT_SETTINGS")
    parser.add_argument("--delay", type=float, default=2.5, help="seconds between model calls in one order")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)
    session = ChatSession(settings={"model": args.model} if args.model else None, delay=args.delay)
    opener = None if args.no_open else (show or webbrowser.open)
    return run(session, port=args.port, out=out, open_page=opener)
