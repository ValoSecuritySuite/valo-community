"""Tiny stand-in for the OpenAI Chat Completions API.

Lets the firewall demo run end-to-end without spending tokens or needing a
real API key. Wire format matches OpenAI exactly, so the customer app and
the Valo proxy cannot tell it apart from the real upstream.

Run: python demo/firewall/fake_openai.py [--port 9999]
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": {"message": "invalid json"}})

        messages = body.get("messages") or []
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        reply = (
            "Hi, I am ACME Support. "
            f"You said: {last_user[:160]}. "
            "Here is a placeholder answer from the upstream LLM."
        )

        payload = {
            "id": f"chatcmpl-fake-{uuid.uuid4().hex[:10]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "fake-model"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": reply},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        self._json(200, payload)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()
    print(f"[fake-openai] listening on http://{args.host}:{args.port}/v1/chat/completions")
    HTTPServer((args.host, args.port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
