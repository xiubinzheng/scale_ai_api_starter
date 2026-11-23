import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from main import app, evaluation_jobs

client = TestClient(app)

OLLAMA_REQUEST = httpx.Request('POST', 'http://localhost:11434/api/chat')


def ollama_reply(score: int = 1, reason: str = 'Correct.') -> httpx.Response:
    content = json.dumps({'score': score, 'reason': reason})
    return httpx.Response(200, json={'message': {'role': 'assistant', 'content': content}}, request=OLLAMA_REQUEST)


def wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError('condition not met before timeout')
        time.sleep(0.01)


def submit(question: str = 'What is the capital of France?') -> str:
    response = client.post('/evaluations', json={
        'question': question, 'generated_answer': 'Paris', 'reference_answer': 'Paris',
    })
    assert response.status_code == 201
    assert response.json()['status'] == 'pending'
    return response.json()['job_id']


def job_status(job_id: str) -> str:
    return client.get(f'/evaluations/{job_id}').json()['status']


def all_finished(job_ids: list[str]) -> bool:
    return all(job_status(job_id) in ('completed', 'failed') for job_id in job_ids)


class FakeOllama:
    """Stands in for httpx.post. Tracks how many requests are in flight at once.

    Each request blocks until `release` is set, so the test controls when calls finish.
    `behavior(question)` may return a response or raise to simulate per-job outcomes.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.total_calls = 0
        self.release = threading.Event()
        self.behavior = lambda question: ollama_reply()

    def post(self, url, json=None, timeout=None):
        question = json['messages'][-1]['content'].splitlines()[0].removeprefix('Question: ')
        with self.lock:
            self.in_flight += 1
            self.total_calls += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            assert self.release.wait(timeout=5), 'test never released the fake Ollama'
            return self.behavior(question)
        finally:
            with self.lock:
                self.in_flight -= 1


@pytest.fixture
def fake_ollama(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(main.httpx, 'post', fake.post)
    evaluation_jobs.clear()
    yield fake
    # Never leave worker threads blocked or running against a cleared job store
    fake.release.set()
    wait_until(lambda: fake.in_flight == 0 and all(
        job.status in ('completed', 'failed') for job in list(evaluation_jobs.values())
    ))
    evaluation_jobs.clear()


def test_requests_overlap_but_never_exceed_limit_of_three(fake_ollama):
    job_ids = [submit(f'question {i}') for i in range(6)]

    # Three Ollama requests are genuinely in flight at the same time
    wait_until(lambda: fake_ollama.in_flight == 3)
    time.sleep(0.2)  # give any extra worker a chance to (wrongly) start a 4th request
    assert fake_ollama.in_flight == 3
    assert fake_ollama.max_in_flight == 3

    # Exactly 3 jobs are running; the rest are waiting as pending
    statuses = [job_status(job_id) for job_id in job_ids]
    assert statuses.count('running') == 3
    assert statuses.count('pending') == 3

    fake_ollama.release.set()
    wait_until(lambda: all_finished(job_ids))

    assert [job_status(job_id) for job_id in job_ids] == ['completed'] * 6
    assert fake_ollama.total_calls == 6
    assert fake_ollama.max_in_flight == 3


def test_post_stays_responsive_while_all_workers_busy(fake_ollama):
    for i in range(3):
        submit(f'busy {i}')
    wait_until(lambda: fake_ollama.in_flight == 3)

    started = time.monotonic()
    waiting_job_id = submit('queued job')
    elapsed = time.monotonic() - started

    assert elapsed < 0.5  # did not wait for a worker (workers are blocked for up to 5s)
    assert job_status(waiting_job_id) == 'pending'

    fake_ollama.release.set()
    wait_until(lambda: job_status(waiting_job_id) == 'completed')


def test_one_failed_job_does_not_affect_others(fake_ollama):
    def behavior(question):
        if question == 'network failure':
            raise httpx.ConnectError('connection refused')
        if question == 'invalid output':
            return ollama_reply(score=7)
        return ollama_reply()

    fake_ollama.behavior = behavior
    questions = ['ok 1', 'network failure', 'ok 2', 'invalid output', 'ok 3', 'ok 4']
    job_ids = {question: submit(question) for question in questions}

    wait_until(lambda: fake_ollama.in_flight == 3)  # failures happen while other jobs are in flight
    fake_ollama.release.set()
    wait_until(lambda: all_finished(list(job_ids.values())))

    for question, job_id in job_ids.items():
        job = client.get(f'/evaluations/{job_id}').json()
        if question in ('network failure', 'invalid output'):
            assert job['status'] == 'failed'
            assert job['error']
        else:
            assert job['status'] == 'completed'
            assert job['result'] == {'score': 1, 'reason': 'Correct.'}

    # Workers are still healthy after failures
    later_job_id = submit('after failures')
    wait_until(lambda: job_status(later_job_id) == 'completed')


def test_job_stays_pending_until_worker_acquires_a_permit(fake_ollama):
    fake_ollama.release.set()  # Ollama answers immediately; only the semaphore can hold the job back
    for _ in range(main.MAX_CONCURRENT_OLLAMA_REQUESTS):
        main.ollama_semaphore.acquire()  # occupy every permit
    try:
        job_id = submit()
        time.sleep(0.2)  # a worker has picked the job up and is blocked on the semaphore
        assert job_status(job_id) == 'pending'
        assert fake_ollama.total_calls == 0
    finally:
        for _ in range(main.MAX_CONCURRENT_OLLAMA_REQUESTS):
            main.ollama_semaphore.release()

    wait_until(lambda: job_status(job_id) == 'completed')


def test_permits_are_released_after_failures(fake_ollama):
    fake_ollama.behavior = lambda question: (_ for _ in ()).throw(httpx.ConnectError('down'))
    failing_job_ids = [submit(f'fail {i}') for i in range(6)]  # 2x the permit count
    fake_ollama.release.set()
    wait_until(lambda: all_finished(failing_job_ids))
    assert {job_status(job_id) for job_id in failing_job_ids} == {'failed'}

    # If any permit leaked, fewer than 3 requests could now be in flight
    fake_ollama.release.clear()
    fake_ollama.behavior = lambda question: ollama_reply()
    healthy_job_ids = [submit(f'ok {i}') for i in range(3)]
    wait_until(lambda: fake_ollama.in_flight == 3)
    fake_ollama.release.set()
    wait_until(lambda: all_finished(healthy_job_ids))
    assert {job_status(job_id) for job_id in healthy_job_ids} == {'completed'}


def test_worker_survives_unexpected_exception(fake_ollama, monkeypatch):
    fake_ollama.release.set()
    original_run_evaluation = main.run_evaluation

    def crash_once(job_id):
        if evaluation_jobs[job_id].question == 'crash':
            raise RuntimeError('unexpected bug outside the evaluation try/except')
        original_run_evaluation(job_id)

    monkeypatch.setattr(main, 'run_evaluation', crash_once)
    crashing_ids = [submit('crash') for _ in range(main.WORKER_COUNT)]  # hit every worker
    main.job_queue.join()
    for job_id in crashing_ids:
        evaluation_jobs[job_id].status = 'failed'  # mark so fixture teardown doesn't wait on them

    job_id = submit('after crash')
    wait_until(lambda: job_status(job_id) == 'completed')
