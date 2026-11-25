"""Local OpenAI-compatible front for Round.model. The API key is not a provider secret."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import HarnessError


class model_transport:
    api_key = "workspace-local-no-secret"

    def __init__(self, rnd):
        if not isinstance(getattr(rnd, "model_name", ""), str) or not rnd.model_name:
            raise HarnessError("MODEL_NAME_REQUIRED")
        self.round = rnd
        self.model_name = rnd.model_name
        self.max_output_tokens = rnd.max_output_tokens
        self.call_ids = rnd.call_ids
        self._server = None
        self._thread = None
        self.base_url = ""

    def __enter__(self):
        if self._server is not None:
            raise HarnessError("TRANSPORT_ALREADY_STARTED")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def _sse(self, response, include_usage):
                envelope = {key: response[key] for key in ("id", "model", "created", "object") if key in response}
                choices = response.get("choices") or []
                deltas = []
                finishes = []
                for position, choice in enumerate(choices):
                    index = choice.get("index", position)
                    message = choice.get("message")
                    delta = dict(message) if isinstance(message, dict) else {}
                    if isinstance(delta.get("tool_calls"), list):
                        delta["tool_calls"] = [
                            {**call, "index": call.get("index", tool_index)}
                            for tool_index, call in enumerate(delta["tool_calls"])
                        ]
                    deltas.append({"index": index, "delta": delta, "finish_reason": None})
                    finish = choice.get("finish_reason") or ("tool_calls" if delta.get("tool_calls") else "stop")
                    finishes.append({"index": index, "delta": {}, "finish_reason": finish})

                def event(value):
                    return ("data: " + json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n\n").encode("utf-8")

                events = [event({**envelope, "choices": deltas}), event({**envelope, "choices": finishes})]
                if include_usage:
                    events.append(event({**envelope, "choices": [], "usage": response.get("usage")}))
                events.append(b"data: [DONE]\n\n")
                body = b"".join(events)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status, value):
                body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path != "/v1/models":
                    self._json(404, {"error": {"message": "operation unavailable"}})
                    return
                self._json(200, {"object": "list", "data": [{
                    "id": owner.model_name, "object": "model", "created": 0, "owned_by": "workspace",
                }]})

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self._json(404, {"error": {"message": "operation unavailable"}})
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                    if length < 0 or length > 1048576:
                        raise ValueError("request exceeds limit")
                    request = json.loads(self.rfile.read(length))
                    if not isinstance(request, dict) or request.get("model") != owner.model_name:
                        raise ValueError("model not bound to this run")
                    stream = request.get("stream") is True
                    if "stream" in request and request.get("stream") not in (True, False):
                        raise ValueError("streaming flag must be boolean")
                    options = {key: value for key, value in request.items() if key not in ("model", "stream", "stream_options")}
                    if "max_completion_tokens" in options:
                        if "max_tokens" in options:
                            raise ValueError("conflicting token limits")
                        options["max_tokens"] = options.pop("max_completion_tokens")
                    messages = options.pop("messages")
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": {"message": str(exc)}})
                    return
                try:
                    receipt = owner.round.model(messages, **options)
                    if stream:
                        stream_options = request.get("stream_options")
                        include_usage = isinstance(stream_options, dict) and stream_options.get("include_usage") is True
                        self._sse(receipt.response, include_usage)
                    else:
                        self._json(200, receipt.response)
                except Exception as exc:
                    self._json(502, {"error": {"message": str(exc)}} )

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = False
        self.base_url = "http://127.0.0.1:%d/v1" % self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join()
            self._server = None
            self._thread = None
