# Walkthrough

- **Goal:** Triage GitHub issues automatically without the bot ever saying something the team
  would regret. It fetches issues through Composio, uses Gemini to classify each one and draft a
  reply, and posts only when every safety rule passes. Everything else is escalated to a human
  and logged.

- **Approach:** "The model suggests, the code decides." Gemini returns structured data (category,
  yes/no evidence, draft reply), checked with Pydantic and re-asked once if invalid. Plain, tested
  Python makes every decision: rules R1–R8 plus a security/money check. Cheap checks run before
  Gemini, and nothing is posted without `--post`. A hidden marker stops double posts. 183 tests,
  no network needed.

- **What broke and how I debugged it:** Confidence was useless: Gemini said 1.00 for nearly
  everything, even "it doesnt work", so the "confidence ≥ 0.70" rule never triggered. I fed it
  8 deliberately ambiguous issues and found its number reflects only doubt about the *category*,
  not whether the issue has enough substance. So I made Gemini answer yes/no questions ("does it
  include an error message?") and compute the score in code. Testing that again showed a second
  flaw: the general answers alone already reached 0.75, so issues passed without any real
  evidence. Lowering the base and tightening the questions fixed it, and the scores became stable
  across runs.

- **How I used AI:** I built it with Claude Code as a pair programmer. I set the requirements and
  made the design calls: which model setup, dropping the self-reported confidence, what to fix
  now vs. later. Claude wrote the code and tests, checked real API shapes before using them, and
  ran repeated "senior dev" reviews that tried to break each phase. Those reviews found a Windows
  encoding crash, R6 missing HTML and bare-domain links, and replies that could @mention
  strangers, all before anything shipped.

- **What's unfinished:** The dry-run reply can differ from the one `--post` sends (planned fix:
  `--post-from log.jsonl`). Escalations are recorded again on every run. Soft promises like "as
  soon as possible" get through, and the confidence weights and security word list haven't been
  tuned on real data. Replies post from my personal account. The full list is in
  [IMPROVEMENTS.md](IMPROVEMENTS.md).
