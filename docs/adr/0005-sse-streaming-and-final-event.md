# 0005: SSE streaming with a final validation event

Status: accepted

## Context
Answers should stream, but `[[Card]]` tags can only be validated against the card database once the full text is known. Feedback also needs the trace id, and citations need to be structured.

## Decision
- Transport: SSE over `POST /conversations/{id}/messages`, consumed with `fetch`. The frontend sends the Supabase JWT and the backend verifies it.
- Events: `start` (message id and trace id), `status` (graph step), `token`, `final` (full text, validated cards, citations) and `error`.
- Validation happens once at the end of generation. During streaming the UI hides the `[[ ]]` markup. On `final`, validated cards become hover previews and unvalidated tags render as plain text.

## Consequences
- The trace id is available from the first event, so feedback can be wired immediately.
- Streaming is of text only. Structured data arrives at the end.
- The frontend needs a streaming parser for POST-based SSE, because `EventSource` does not support `POST`.
