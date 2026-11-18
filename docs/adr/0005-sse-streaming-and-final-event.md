# 0005: SSE streaming with a final validation event

Status: accepted

## Context
Answers should stream, but `[[Card]]` tags can only be validated against the card database once the full text is known. Feedback also needs the trace id, and citations need to be structured.

## Decision
- Transport: SSE over `POST /conversations/{id}/messages`, consumed with `fetch`. The frontend sends the Supabase JWT and the backend verifies it.
- Events: `start` (message id and trace id), `status` (graph step), `token`, `reset`, `final` (full text, validated cards, citations) and `error`.
- `reset` (added 2026-11-17, after review) tells the client to discard the text streamed so far. The agent sends it when a reply it was streaming is thrown away: a provider failed mid-reply and the next one starts over, or the model wrote text and then called a tool instead of answering. Without it the client would show two replies run together until `final` arrived.
- Validation happens once at the end of generation. During streaming the UI hides the `[[ ]]` markup. On `final`, validated cards become hover previews and unvalidated tags render as plain text.
- Stored answers keep only their text (added 2026-11-17, after review). Reading a conversation validates each answer's tags again and returns them as that message's `cards`, so a reload shows the same previews.

## Consequences
- The trace id is available from the first event, so feedback can be wired immediately.
- Streaming is of text only. Structured data arrives at the end.
- The frontend needs a streaming parser for POST-based SSE, because `EventSource` does not support `POST`.
