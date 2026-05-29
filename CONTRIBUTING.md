# Contributing to Valo

Thank you for contributing to Valo Community Edition.

## Development setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests

```bash
pytest tests/test_edition_community.py tests/test_api.py tests/test_pipeline.py -v
python scripts/community_smoke.py
```

## Pull requests

- Keep changes focused and include tests for behavior changes.
- Ensure `docker compose up --build` remains a valid quick-start path.
- Do not commit secrets, `.env` files, or `data/` artifacts.
- Update documentation when adding or changing public API surface.
