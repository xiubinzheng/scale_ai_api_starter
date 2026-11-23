#!/usr/bin/env bash
# Submit a batch of evaluation jobs, watch their statuses, then print the results.
# Usage: ./scripts/submit_jobs.sh [COPIES]
#   COPIES  how many times to submit the question list (default 1 = 10 jobs)
# Optional env var: BASE_URL (default http://127.0.0.1:8000)
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
COPIES="${1:-1}"

QUESTIONS=(
  "What is the capital of France?|Paris|Paris"
  "What is 2 + 2?|5|4"
  "Who wrote Hamlet?|Shakespeare|William Shakespeare"
  "What is the boiling point of water in Celsius?|100|100 degrees"
  "What planet is known as the Red Planet?|Venus|Mars"
  "What is the largest ocean?|Pacific|Pacific Ocean"
  "How many continents are there?|7|Seven"
  "What gas do plants absorb?|Oxygen|Carbon dioxide"
  "What is the square root of 81?|9|9"
  "Who painted the Mona Lisa?|Da Vinci|Leonardo da Vinci"
)

json_field() {
  python3 -c "import sys, json; print(json.load(sys.stdin).get('$1', ''))"
}

if ! curl -s -o /dev/null "$BASE_URL/docs"; then
  echo "Server not reachable at $BASE_URL. Start it with ./scripts/start_server.sh" >&2
  exit 1
fi

# 1. Submit
JOB_IDS=()
for ((copy = 1; copy <= COPIES; copy++)); do
  for entry in "${QUESTIONS[@]}"; do
    IFS='|' read -r question generated reference <<< "$entry"
    JOB_ID=$(curl -s -X POST "$BASE_URL/evaluations" \
      -H 'Content-Type: application/json' \
      -d "{\"question\": \"$question\", \"generated_answer\": \"$generated\", \"reference_answer\": \"$reference\"}" \
      | json_field job_id)
    JOB_IDS+=("$JOB_ID")
  done
done
echo "Submitted ${#JOB_IDS[@]} jobs"
echo

# 2. Watch statuses until every job is completed or failed
while true; do
  PENDING=0; RUNNING=0; COMPLETED=0; FAILED=0
  for id in "${JOB_IDS[@]}"; do
    case "$(curl -s "$BASE_URL/evaluations/$id" | json_field status)" in
      pending)   PENDING=$((PENDING + 1)) ;;
      running)   RUNNING=$((RUNNING + 1)) ;;
      completed) COMPLETED=$((COMPLETED + 1)) ;;
      failed)    FAILED=$((FAILED + 1)) ;;
    esac
  done
  printf '%s  pending=%-3d running=%-3d completed=%-3d failed=%-3d\n' \
    "$(date +%T)" "$PENDING" "$RUNNING" "$COMPLETED" "$FAILED"
  [[ $((COMPLETED + FAILED)) -eq ${#JOB_IDS[@]} ]] && break
  sleep 0.5
done
echo

# 3. Results
for id in "${JOB_IDS[@]}"; do
  curl -s "$BASE_URL/evaluations/$id" | python3 -c '
import sys, json
job = json.load(sys.stdin)
result = job.get("result") or {}
status = job["status"]
score = result.get("score", "-")
question = job["question"][:45]
detail = result.get("reason") or job.get("error", "")
print(f"{status:<10} score={score}  {question:<45}  {detail}")'
done
