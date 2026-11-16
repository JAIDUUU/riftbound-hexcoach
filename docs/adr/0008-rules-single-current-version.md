# 0008: Keep only the current rules version

Status: accepted

## Context
The rules document changes over time, and the FAQs are dated. Supporting several rules versions would complicate retrieval, citations and evaluation.

## Decision
Keep only the current rules version, stored with its version and date. FAQs keep their own dates. Updating the rules means a re-ingest and a golden-set re-run.

## Consequences
- Answers always reflect the current rules. Questions about older rulings are not supported.
- The golden set must be reviewed whenever the rules change, because expected rule numbers can move.
- Git history is the only record of earlier rules versions.
