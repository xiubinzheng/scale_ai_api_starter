# Backend Coding Interview

## Tech Stack
- Python 3
- FastAPI for HTTP endpoints
- pytest for testing
- httpx for external HTTP requests
- Pydantic for request/response validation
- Python standard library for CSV and JSON processing

## Coding Guidelines
- Prioritize working code over perfect architecture.
- Implement the simplest solution that satisfies requirements.
- Keep functions small, readable, and testable.
- Use descriptive variable names.
- Avoid unnecessary abstractions, frameworks, and dependencies.
- Do not introduce databases, queues, or Docker unless required.
- Prefer synchronous code unless concurrency is needed.

## API Development
- Use FastAPI with Pydantic models.
- Return appropriate HTTP status codes.
- Handle invalid inputs and missing files.
- Set explicit timeouts on external HTTP requests.
- Validate untrusted external API and LLM responses.
- Read API keys from environment variables.

## Testing
- Use pytest and FastAPI TestClient.
- Test successful requests and important failure cases.
- Mock external API calls when appropriate.
- Run tests after modifying functionality.
- Never modify tests just to make incorrect code pass.

## Interview Workflow
- Implement requirements incrementally.
- Focus only on the current interviewer requirement.
- Do not anticipate or implement unrequested features.
- Prefer minimal code changes over major rewrites.
- Explain implementation decisions concisely in a few bullet points.
- When reporting completion, summarize what changed
  and whether tests passed.