import pytest
from fastapi.testclient import TestClient

import main
from main import app, evaluation_jobs

client = TestClient(app)

VALID_PAYLOAD = {
    'question': 'What is the capital of France?',
    'generated_answer': 'Paris',
    'reference_answer': 'Paris',
}


@pytest.fixture(autouse=True)
def clear_jobs():
    evaluation_jobs.clear()
    yield
    evaluation_jobs.clear()


@pytest.fixture(autouse=True)
def disable_background_evaluation(monkeypatch):
    # These tests cover submission/retrieval only; LLM evaluation is tested in test_llm_evaluation.py
    monkeypatch.setattr(main, 'run_evaluation', lambda job_id: None)


def test_create_evaluation_returns_201_with_pending_status():
    response = client.post('/evaluations', json=VALID_PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body['status'] == 'pending'
    assert isinstance(body['job_id'], str) and body['job_id']
    assert set(body.keys()) == {'job_id', 'status'}


def test_each_submission_gets_unique_job_id():
    job_ids = {client.post('/evaluations', json=VALID_PAYLOAD).json()['job_id'] for _ in range(5)}
    assert len(job_ids) == 5


def test_get_evaluation_returns_stored_job():
    job_id = client.post('/evaluations', json=VALID_PAYLOAD).json()['job_id']
    response = client.get(f'/evaluations/{job_id}')
    assert response.status_code == 200
    assert response.json() == {'job_id': job_id, 'status': 'pending', **VALID_PAYLOAD}


def test_get_unknown_job_returns_404():
    response = client.get('/evaluations/does-not-exist')
    assert response.status_code == 404


@pytest.mark.parametrize('field', ['question', 'generated_answer', 'reference_answer'])
def test_missing_field_returns_422(field):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != field}
    response = client.post('/evaluations', json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize('field', ['question', 'generated_answer', 'reference_answer'])
@pytest.mark.parametrize('bad_value', ['', '   ', None, 123, ['Paris']])
def test_invalid_field_value_returns_422(field, bad_value):
    payload = {**VALID_PAYLOAD, field: bad_value}
    response = client.post('/evaluations', json=payload)
    assert response.status_code == 422


def test_invalid_input_does_not_store_job():
    client.post('/evaluations', json={**VALID_PAYLOAD, 'question': ''})
    assert evaluation_jobs == {}
