# 45-minute practice exercise (intentionally unsolved)

## Part 1: CSV -> JSON (15 minutes)
Implement `POST /convert` in `main.py`.

- Read `data/input.csv` with `csv.DictReader`.
- Write the records to `data/output.json`.
- Return `{ "count": 3, "output_file": "data/output.json" }`.
- Handle missing inputs clearly (HTTP 404 or 400).
- Add tests using pytest, ideally with a temporary directory (`tmp_path`).

## Part 2: Classify records (15 minutes)
Implement `POST /classify` that takes JSON like:

```json
{"records": [{"id": "1", "text": "Very helpful answer"}]}
```

- Produce `{"results": [{"id": "1", "label": "positive"}]}`.
- First use a simple deterministic fake classifier.
- Then replace it with a function that would call an HTTP/LLM API, if a safe test key is available.
- Validate output fields and labels before returning them.

## Part 3: Robustness (15 minutes)
- Test malformed JSON, empty CSV, missing text field, unexpected labels.
- Simulate a 429, timeout, and 500 from the external API; explain where retries belong.
- Explain what would change for thousands of records (batching, bounded concurrency, progress tracking).

Keep the requirements simple. Narrate your tradeoffs and run tests throughout.
