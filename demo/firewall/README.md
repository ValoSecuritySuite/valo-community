# Valo AI Firewall: Real-World Demo

A turn-key, end-to-end demo of the Valo AI Firewall using a stand-in
"customer support" application. No Playground, no synthetic
`/enforcement/simulate` calls: the customer app talks to the real
`POST /v1/proxy/chat/completions` proxy exactly the way a paying
customer would.

## What is in this folder

| File              | Role                                                                 |
|-------------------|----------------------------------------------------------------------|
| `fake_openai.py`  | Drop-in mock of OpenAI Chat Completions on `:9999`. No API key needed. |
| `customer_app.py` | "ACME Support" chatbot using the real `openai` Python SDK. Zero Valo-specific code. |
| `scenarios.py`    | Drives the customer app through 4 realistic prompts and prints the audit trail. |
| `run_demo.sh`     | Boots fake upstream + Valo in enforce mode, runs scenarios, tears down. |

## Prerequisites

```bash
pip install -r requirements.txt
pip install openai
```

## Run it (no API key needed)

```bash
bash demo/firewall/run_demo.sh
```

You will see four customer interactions:

1. A normal product question gets a real upstream answer (allow).
2. A receipt to a customer email is delivered, headers show `warn`.
3. A prompt that contains `password=` and `api_key=` is blocked at ingress
   (the upstream is never contacted, no tokens spent).
4. A prompt-injection / system-prompt-extraction attempt is blocked.

After scenarios run, the script prints `/enforcement/stats` and the last
events from `/enforcement/events`, which is the live ops view a SOC analyst
would consume from the dashboard.

## Run it against real OpenAI

```bash
USE_REAL_OPENAI=1 OPENAI_API_KEY=sk-... bash demo/firewall/run_demo.sh
```

Same scenarios, same outputs. The only difference is the upstream calls
actually go to OpenAI for the allowed cases.

## Run the customer app interactively

While Valo is running (`uvicorn app.main:app ...`):

```bash
OPENAI_BASE_URL=http://localhost:8000/v1/proxy \
OPENAI_API_KEY=sk-test-anything \
  python demo/firewall/customer_app.py
```

You get a `you>` prompt. Try anything; allowed prompts return an answer,
denied prompts return `Blocked by Valo (HTTP 403)` plus the matched
policy ids.

## Talk track for live demos

1. **Show the customer app code.** Highlight that the only Valo-specific
   line is `OPENAI_BASE_URL`. No SDK swap, no shim, no wrapper.
2. **Run a normal query.** "Looks like a regular OpenAI call. The firewall
   is invisible when there is nothing to do."
3. **Run an attack query.** "Customer never reaches OpenAI. We do not pay
   for the call, and the attacker gets a structured deny response, not a
   leaked system prompt."
4. **Show the dashboard / `/enforcement/events`.** "Every decision is
   audited. SOC sees this in real time."
5. **Flip enforcement to `monitor`** (rollout story):

   ```bash
   curl -X PATCH http://localhost:8000/enforcement/config \
     -H 'Content-Type: application/json' \
     -d '{"enforcement_mode":"monitor"}'
   ```

   Re-run the attack. Now it returns `200`, but headers carry
   `X-Valo-Policy-Decision: deny` and the event log shows
   `blocked: false` with reason `would_block`. "This is how customers
   stage the rollout: observe in production for two weeks, then flip to
   `enforce` once they trust the policies."
6. **Add a new policy.** Drop a new YAML file under
   `app/policies/governance/`, then `POST /policies/reload`, and re-run
   the customer app to show the new control taking effect immediately.

## Why no Playground

The Playground (`POST /enforcement/simulate`) is for authoring policies
and dry-running prompts during development. Real-world enforcement uses
`POST /v1/proxy/chat/completions`, which is the only thing this demo
touches. Customers never call the simulate endpoint from production.
