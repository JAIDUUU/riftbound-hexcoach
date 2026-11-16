# 0004: assistant-ui primitives with our own CSS, no Tailwind or shadcn

Status: accepted

## Context
The chat UI needs custom behavior: `[[Card]]` hover previews, `@` mentions for cards and decks, feedback tied to a trace id, and streaming from our own SSE endpoint. The look is not decided yet. assistant-ui provides chat primitives and runtimes, and its prebuilt styled components are built around Tailwind and shadcn.

## Decision
- Use Vite + React + TypeScript with TanStack Query and assistant-ui **primitives** (unstyled).
- Do not use Tailwind or shadcn. Define our own CSS tokens and the aesthetics later.
- Connect our backend through a custom runtime adapter. The trace id, validated cards and citations travel in message metadata.

## Consequences
- We write all styling ourselves, but nothing fights the primitives.
- Support for plain CSS with every primitive has not been verified. Check this at the start of the frontend milestone.
- The design tokens must be defined before the chat UI is polished.
