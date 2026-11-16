# 0003: Prompts live in the repo only

Status: accepted

## Context
Langfuse can manage prompts, but we also need the demo to work if Langfuse is unavailable. Langfuse is already used for tracing, datasets, experiments and feedback scores.

## Decision
Prompts are kept in the repo and versioned with the code. Langfuse is not used for prompt management.

## Consequences
- Prompt changes go through code review and CI like any other change.
- There is no runtime dependency on Langfuse for prompts.
- The Langfuse "prompt management" feature is not showcased. Experiment results can still be tied to a git commit.
