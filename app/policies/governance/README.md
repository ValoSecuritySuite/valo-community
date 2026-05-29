# Governance policy examples

These YAML files ship with Valo Community Edition as **examples**.

- Policies evaluate pipeline context (scores, signals, matched rules).
- `then.decision` is `allow`, `warn`, or `deny`.
- `enforce: true` blocks HTTP traffic only when enforcement mode is `enforce`
  (Valo Enterprise). In Community Edition, enforcement runs in **monitor** mode:
  denials appear in response headers and logs without blocking the request.

Customize policies for your environment; reload via `POST /policies/reload`.
