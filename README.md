# Scale AI local API interview starter

Python + FastAPI + pytest + httpx. Two working endpoints and three passing tests.

## Prerequisites

Python 3.10+ recommended. Use these commands from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn main:app --reload --port 8000
```

In another terminal:

```bash
curl -i http://127.0.0.1:8000/hello_world
curl -i -X POST http://127.0.0.1:8000/echo \
  -H 'Content-Type: application/json' -d '{"text":"test"}'
```

Expected GET response: HTTP 200 and `{ "hello": "world" }`.

Browse `http://127.0.0.1:8000/docs` for FastAPI's interactive API documentation.

## Included files

- `main.py` - hello-world and echo endpoints
- `tests/test_main.py` - pytest smoke test and API endpoint tests
- `helpers.py` - CSV read, JSON write, outbound HTTP GET examples
- `data/input.csv` - sample input for the exercise
- `practice.md` - unsolved timed practice exercise

## Tips

- Keep the server in one terminal and tests/curl in another.
- Read error bodies and tracebacks.
- Always use HTTP timeouts for external services.
- Use environment variables for API keys; do not commit or share them.
# scale_ai_api_starter
