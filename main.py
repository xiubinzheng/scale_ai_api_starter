import json
import logging
import os
import queue
import threading
import uuid
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.2:3b')
OLLAMA_TIMEOUT_SECONDS = 60.0
MAX_CONCURRENT_OLLAMA_REQUESTS = 3
WORKER_COUNT = 5  # more workers than permits: the semaphore, not the worker count, enforces the limit

logger = logging.getLogger(__name__)

# Producer/worker plumbing (process-wide)
job_queue: queue.Queue[str] = queue.Queue()
ollama_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_OLLAMA_REQUESTS)

app = FastAPI()


class EchoRequest(BaseModel):
    text: str


@app.get('/hello_world')
def hello_world():
    return {'hello': 'world'}


@app.post('/echo')
def echo(payload: EchoRequest):
    return {'text': payload.text}


# --- Evaluation jobs ---

class EvaluationRequest(BaseModel):
    question: str
    generated_answer: str
    reference_answer: str

    @field_validator('question', 'generated_answer', 'reference_answer')
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must be a nonempty string')
        return value


class EvaluationCreatedResponse(BaseModel):
    job_id: str
    status: str


class EvaluationResult(BaseModel):
    # strict=True rejects booleans and numeric strings like "1"
    score: Annotated[int, Field(strict=True, ge=0, le=1)]
    reason: str

    @field_validator('reason')
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('reason must be a nonempty string')
        return value


class EvaluationJob(BaseModel):
    job_id: str
    question: str
    generated_answer: str
    reference_answer: str
    status: str  # pending -> running -> completed | failed
    result: EvaluationResult | None = None
    error: str | None = None


# In-memory storage: job_id -> EvaluationJob
evaluation_jobs: dict[str, EvaluationJob] = {}


JUDGE_SYSTEM_PROMPT = (
    'You are a strict grader. Compare the generated answer to the reference answer '
    'for the given question. Respond with JSON only: '
    '{"score": 1, "reason": "..."} if the generated answer is correct (matches the '
    'reference in meaning), or {"score": 0, "reason": "..."} if it is incorrect. '
    'The reason must briefly explain the judgment.'
)


def build_ollama_request(job: EvaluationJob) -> dict:
    user_prompt = (
        f'Question: {job.question}\n'
        f'Generated answer: {job.generated_answer}\n'
        f'Reference answer: {job.reference_answer}'
    )
    return {
        'model': OLLAMA_MODEL,
        'stream': False,
        'format': EvaluationResult.model_json_schema(),
        'options': {'temperature': 0},
        'messages': [
            {'role': 'system', 'content': JUDGE_SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt},
        ],
    }


def call_ollama_judge(job: EvaluationJob) -> EvaluationResult:
    """Call Ollama and validate its reply. Raises on HTTP or validation errors."""
    response = httpx.post(
        f'{OLLAMA_URL}/api/chat',
        json=build_ollama_request(job),
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    content = response.json()['message']['content']
    return EvaluationResult.model_validate(json.loads(content))


def run_evaluation(job_id: str) -> None:
    """Run one evaluation. Caller must already hold an Ollama permit."""
    job = evaluation_jobs[job_id]
    job.status = 'running'
    try:
        job.result = call_ollama_judge(job)
        job.status = 'completed'
    except Exception as error:  # any failure must mark the job failed
        job.error = f'{type(error).__name__}: {error}'
        job.status = 'failed'


def enqueue_job(job_id: str) -> None:
    """Producer: hand the job to the workers. Never blocks (queue is unbounded)."""
    job_queue.put(job_id)


def process_job(job_id: str) -> None:
    # Acquire capacity BEFORE the job becomes "running"; jobs waiting here stay "pending".
    # `with` releases the permit after processing, including on failure.
    with ollama_semaphore:
        run_evaluation(job_id)


def worker_loop() -> None:
    while True:
        job_id = job_queue.get()
        try:
            process_job(job_id)
        except Exception:  # keep the worker alive for subsequent jobs
            logger.exception('worker failed while processing job %s', job_id)
        finally:
            job_queue.task_done()


def start_workers() -> None:
    for worker_number in range(WORKER_COUNT):
        threading.Thread(target=worker_loop, name=f'evaluation-worker-{worker_number}', daemon=True).start()


start_workers()


@app.post(
    '/evaluations',
    status_code=status.HTTP_201_CREATED,
    response_model=EvaluationCreatedResponse,
)
def create_evaluation(payload: EvaluationRequest):
    job = EvaluationJob(job_id=str(uuid.uuid4()), status='pending', **payload.model_dump())
    evaluation_jobs[job.job_id] = job
    enqueue_job(job.job_id)
    return EvaluationCreatedResponse(job_id=job.job_id, status='pending')


@app.get('/evaluations/{job_id}', response_model=EvaluationJob, response_model_exclude_none=True)
def get_evaluation(job_id: str):
    job = evaluation_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Evaluation job not found')
    return job
