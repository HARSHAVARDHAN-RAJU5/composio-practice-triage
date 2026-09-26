1. use composio github toolkit
2. get issues (headline, body, label author)
3. gemini to find the bug, feature, unclear, qn - give it confidence
4. backend
use python, keep it simple and follow this rules
# Rule Why
R1 Category is not unclear The model admits it doesn't know
R2 Confidence is 0.70 or higher Low confidence goes to a human
R3 Reply is 20-150 words Not empty, not an essay
R4 Reply mentions the issue number or a word from the title Proves it is about this issue
R5 Reply makes no promises: e.g. "will be fixed", "by tomorrow",
"guarantee", "refund"
Never commit the team to anything
R6 Reply contains no links except to the same repository No hallucinated or unsafe URLs
R7 Issue body is not empty and the issue is open Nothing to triage otherwise
5. add escalte and mark escalation.jsonl 
6. log everything in log.jsonl
7. print human readable result

# Failure
Failure Expected behaviour
GitHub not connected in Composio / auth
missing
Clear message telling the user how to connect. No crash or stack trace.
Gemini returns 503 / rate limit Retry with backoff (max 3), then fall back to the second model. Log which
model answered.
Gemini returns invalid JSON or a bad
category
Validate it (e.g. Pydantic). Re-ask once. If it is still bad, ESCALATE.
Composio tool call fails (bad URL, 404,
network)
Friendly error with the cause. The run is still logged, with decision =
error.
Invalid issue URL passed Rejected before any network call

these are main failure behaviour. i will write if something is needed or needs change

triage/
  tools/    # external actions: fetch issues, post comments via Composio, write escalations.jsonl
  llm/      # model calls: prompts, classifying the issue, drafting replies
  rules/    # deterministic checks: e.g. "security keywords → always ESCALATE", label rules
  cli.py    # entry point: flags like --post, which repo, dry-run vs live

i want clean folder structure keep this as skelton and 