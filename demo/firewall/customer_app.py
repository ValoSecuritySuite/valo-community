"""ACME Customer Support: a stand-in 'real customer app' for the firewall demo.

Uses the real ``openai`` Python SDK with no Valo-specific code. The only
thing pointing it at Valo is ``OPENAI_BASE_URL``, exactly how a customer
would integrate Valo into their existing stack.

Usage:

    OPENAI_BASE_URL=http://localhost:8000/v1/proxy \\
    OPENAI_API_KEY=sk-test-anything \\
        python demo/firewall/customer_app.py "How do I reset my password?"

If you omit a question, an interactive prompt opens.
"""

from __future__ import annotations

import os
import sys
from typing import Any

try:
    from openai import APIStatusError, OpenAI
except ImportError:
    sys.stderr.write(
        "The 'openai' package is required. Install with: pip install openai\n"
    )
    sys.exit(2)


SYSTEM_PROMPT = (
    "You are ACME Support, a helpful customer support agent. "
    "Answer the user concisely and stay on topic."
)


def _client() -> OpenAI:
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", "sk-test-anything"),
    )


def _valo_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {k: v for k, v in items if str(k).lower().startswith("x-valo-")}


def ask(question: str, *, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """Send one user question to the configured upstream and return a result.

    Returns a dict with one of two shapes:
      {"ok": True,  "answer": str, "headers": {...}}
      {"ok": False, "status": int, "error": dict, "headers": {...}}
    """
    client = _client()
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )
        answer = completion.choices[0].message.content or ""
        headers = _valo_headers(getattr(completion, "_response", None) and completion._response.headers)
        return {"ok": True, "answer": answer, "headers": headers}
    except APIStatusError as exc:
        body = exc.body if isinstance(exc.body, dict) else {"message": str(exc.body)}
        return {
            "ok": False,
            "status": exc.status_code,
            "error": body,
            "headers": _valo_headers(getattr(exc, "response", None) and exc.response.headers),
        }
    except Exception as exc:
        return {"ok": False, "status": 0, "error": {"message": str(exc)}, "headers": {}}


def _print_result(question: str, result: dict[str, Any]) -> None:
    print(f"\n>>> Customer: {question}")
    if result["ok"]:
        print(f"<<< ACME Support: {result['answer']}")
    else:
        print(f"<<< Blocked by Valo (HTTP {result['status']}):")
        err = result["error"]
        if isinstance(err, dict):
            detail = err.get("error", err).get("detail") if isinstance(err.get("error"), dict) else None
            if detail and isinstance(detail, dict):
                msg = err.get("error", {}).get("message") or err.get("message", "")
                print(f"    message: {msg}")
                print(f"    matched_policy_ids: {detail.get('matched_policy_ids')}")
                print(f"    side: {detail.get('side')}  trace_id: {detail.get('trace_id')}")
            else:
                print(f"    {err}")
        else:
            print(f"    {err}")
    if result["headers"]:
        print(f"    valo headers: {result['headers']}")


def main() -> None:
    if len(sys.argv) > 1:
        _print_result(sys.argv[1], ask(sys.argv[1]))
        return
    print("ACME Support (Ctrl+C to quit)")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            continue
        _print_result(q, ask(q))


if __name__ == "__main__":
    main()
