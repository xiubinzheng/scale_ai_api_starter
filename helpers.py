"""Optional reference utilities for common interview tasks."""
import csv
import json
from pathlib import Path

import httpx


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_json(path: str | Path, data: object) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def get_external_json(url: str) -> object:
    # Use an interviewer-approved URL; never log API secrets.
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()
