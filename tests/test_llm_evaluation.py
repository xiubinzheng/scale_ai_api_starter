import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from main import EvaluationJob, app, evaluation_jobs

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


def ollama_reply(content: str, status_code: int = 200) -> httpx.Response:
    """Build a response shaped like Ollama's /api/chat (stream=false)."""
    return httpx.Response(
        status_code,
        json={'model': 'test', 'message': {'role': 'assistant', 'content': content}, 'done': True},
        request=httpx.Request('POST', 'http://localhost:11434/api/chat'),
    )


@pytest.fixture
def fake_ollama(monkeypatch):
    """Replace httpx.post; records each request and returns the configured reply."""
    state = {'calls': [], 'reply': ollama_reply(json.dumps({'score': 1, 'reason': 'Correct.'}))}

    def fake_post(url, json=None, timeout=None):
        state['calls'].append({'url': url, 'json': json, 'timeout': timeout})
        if isinstance(state['reply'], Exception):
            raise state['reply']
        return state['reply']

    monkeypatch.setattr(main.httpx, 'post', fake_post)
    return state


def wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError('condition not met before timeout')
        time.sleep(0.01)


def fetch_job(job_id: str) -> dict:
    response = client.get(f'/evaluations/{job_id}')
    assert response.status_code == 200
    return response.json()


def wait_for_job_to_finish(job_id: str) -> dict:
    wait_until(lambda: fetch_job(job_id)['status'] in ('completed', 'failed'))
    return fetch_job(job_id)


def submit_and_fetch() -> tuple[dict, dict]:
    """Submit a job and return (POST body, final job state once the worker finishes)."""
    created = client.post('/evaluations', json=VALID_PAYLOAD)
    assert created.status_code == 201
    return created.json(), wait_for_job_to_finish(created.json()['job_id'])


# --- Successful evaluation ---

def test_successful_evaluation_is_stored_and_retrievable(fake_ollama):
    created, job = submit_and_fetch()

    assert created['status'] == 'pending'
    assert job == {
        'job_id': created['job_id'],
        **VALID_PAYLOAD,
        'status': 'completed',
        'result': {'score': 1, 'reason': 'Correct.'},
    }


def test_incorrect_answer_score_zero(fake_ollama):
    fake_ollama['reply'] = ollama_reply(json.dumps({'score': 0, 'reason': 'Wrong city.'}))
    _, job = submit_and_fetch()
    assert job['status'] == 'completed'
    assert job['result'] == {'score': 0, 'reason': 'Wrong city.'}


def test_one_ollama_request_per_evaluation_with_job_content(fake_ollama):
    submit_and_fetch()
    submit_and_fetch()

    assert len(fake_ollama['calls']) == 2
    call = fake_ollama['calls'][0]
    assert call['url'] == 'http://localhost:11434/api/chat'
    assert call['timeout'] is not None
    assert call['json']['stream'] is False
    user_message = call['json']['messages'][-1]['content']
    for value in VALID_PAYLOAD.values():
        assert value in user_message


# --- Failures ---

@pytest.mark.parametrize('error', [
    httpx.ConnectError('connection refused'),
    httpx.ReadTimeout('timed out'),
])
def test_ollama_network_error_marks_job_failed(fake_ollama, error):
    fake_ollama['reply'] = error
    _, job = submit_and_fetch()
    assert job['status'] == 'failed'
    assert job['error']
    assert 'result' not in job


def test_ollama_http_error_marks_job_failed(fake_ollama):
    fake_ollama['reply'] = ollama_reply('', status_code=500)
    _, job = submit_and_fetch()
    assert job['status'] == 'failed'
    assert '500' in job['error']


@pytest.mark.parametrize('content', [
    'not json at all',
    json.dumps({'score': 1}),                          # missing reason
    json.dumps({'reason': 'ok'}),                      # missing score
    json.dumps({'score': 2, 'reason': 'ok'}),          # out of range
    json.dumps({'score': -1, 'reason': 'ok'}),
    json.dumps({'score': '1', 'reason': 'ok'}),        # string, not int
    json.dumps({'score': True, 'reason': 'ok'}),       # bool, not int
    json.dumps({'score': 0.5, 'reason': 'ok'}),
    json.dumps({'score': 1, 'reason': ''}),            # empty reason
    json.dumps({'score': 1, 'reason': '   '}),
    json.dumps({'score': 1, 'reason': 5}),
    json.dumps(['score', 1]),                          # not an object
])
def test_invalid_llm_output_marks_job_failed(fake_ollama, content):
    fake_ollama['reply'] = ollama_reply(content)
    _, job = submit_and_fetch()
    assert job['status'] == 'failed'
    assert job['error']
    assert 'result' not in job


def test_malformed_ollama_envelope_marks_job_failed(fake_ollama):
    fake_ollama['reply'] = httpx.Response(
        200, json={'unexpected': 'shape'},
        request=httpx.Request('POST', 'http://localhost:11434/api/chat'),
    )
    _, job = submit_and_fetch()
    assert job['status'] == 'failed'
    assert job['error']


# --- Background execution and state transitions ---

def test_post_enqueues_job_via_producer(monkeypatch):
    enqueued = []
    monkeypatch.setattr(main, 'enqueue_job', enqueued.append)

    created = client.post('/evaluations', json=VALID_PAYLOAD).json()

    assert created['status'] == 'pending'
    assert enqueued == [created['job_id']]
    assert evaluation_jobs[created['job_id']].status == 'pending'


def test_job_is_running_while_llm_call_in_progress(monkeypatch):
    job_id = 'job-1'
    evaluation_jobs[job_id] = EvaluationJob(job_id=job_id, status='pending', **VALID_PAYLOAD)
    observed_statuses = []

    def fake_judge(job):
        observed_statuses.append(evaluation_jobs[job_id].status)
        return main.EvaluationResult(score=1, reason='Correct.')

    monkeypatch.setattr(main, 'call_ollama_judge', fake_judge)
    main.run_evaluation(job_id)

    assert observed_statuses == ['running']
    assert evaluation_jobs[job_id].status == 'completed'


def test_pending_job_has_no_result_or_error(monkeypatch):
    monkeypatch.setattr(main, 'run_evaluation', lambda job_id: None)
    job = fetch_job(client.post('/evaluations', json=VALID_PAYLOAD).json()['job_id'])
    assert job['status'] == 'pending'
    assert 'result' not in job and 'error' not in job


# --- Optional live check against a real local Ollama ---

def ollama_is_available() -> bool:
    try:
        return httpx.get(f'{main.OLLAMA_URL}/api/tags', timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not ollama_is_available(), reason='local Ollama not running')
def test_live_ollama_evaluation():
    _, job = submit_and_fetch()
    assert job['status'] == 'completed', job.get('error')
    assert job['result']['score'] in (0, 1)
    assert job['result']['reason'].strip()
