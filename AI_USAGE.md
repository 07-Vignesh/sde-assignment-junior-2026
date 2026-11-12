# AI Usage Disclosure

## Tools used
Claude (chat interface). I used it as a step-by-step guide for the whole assignment.

## What I used them for
- Understanding the assignment, and planning the order of work: normalisers, schema loader, database and PII, lead ingestion, event ingestion, derived facts, reports, CLI, idempotency check, documents.
- Drafting the code and tests for every module in `pipeline/` and `tests/`, and `check_idempotency.py`.
- Drafting `README_SOLUTION.md`, `SUBMISSION.md` and this file.
- Explaining Git, virtual environments and VS Code steps.

Most of the code in this repo was written by Claude. I pasted it in, ran it and committed it step by step.

## What I wrote or decided myself
- I forked and cloned the repo, set up the environment, generated the data and read the schemas, dispositions and sample CSV/JSONL files.
- I ran every test and the pipeline on the generated data, and I chose when to commit.
- I decided to keep the repo's existing `.gitignore`, `SUBMISSION.md` and `AI_USAGE.md` and fill them in rather than overwrite them.
- <<Add anything that is really yours, for example a design choice you understood and agreed with, such as "linking events to leads at report time". If the design was mostly Claude's, say so.>>

## Where the AI was wrong or unhelpful
- It told me to run `pip install` after `python -m venv .venv` without activating the venv (the activation lines were comments), so packages went into global Python. I noticed from the pip output, which said "Requirement already satisfied" with a global path. I then activated the venv and checked `sys.executable`.
- It first told me to create `.gitignore`, `SUBMISSION.md` and `README.md` from scratch, but the repo already had some of them. I found out from the files that existed and filled in the templates instead.
- It said "8 passed" when the real count was 9. I saw the real pytest output.
- <<Add any other mistake you found, or write that you found no others.>>

## How I verified AI-generated code
- Ran `pytest` after every step (50 tests pass).
- Ran the pipeline on the generated data and checked that counts add up: 8745 event lines = 8500 stored + 8 malformed + 237 duplicates, and 2057 lead rows - 108 rejected - 57 merged = 1892 leads.
- Checked that report totals agree across files: 1892 leads and 2536 calls in both the per-lead and the summary reports.
- Ran `check_idempotency.py`: re-ingesting everything, events ingested before leads, and the baseline all gave identical report files.
- Re-ran ingest by hand and diffed two report folders with `fc.exe`.
- Not done: a second seed, the large data set, and an independent implementation to compare against. <<Add whether you read the code line by line, and how much of it you can explain.>>