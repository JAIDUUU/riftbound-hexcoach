# HexCoach: Glossary

Domain terms used across the code and docs. See [Grill Decisions.md](Grill%20Decisions.md) for the decisions behind them.

## Cards

- **Card:** a distinct Riftbound card, identified by its `oracle_id`. All printings of the same card are the same Card, because card text is identical.
- **Printing:** one physical version of a Card (plain, Metal, alternate art, overnumbered, signature). Rifthunt gives each a `printing_id`. We collapse printings into the plain one.
- **Oracle id:** the id shared by every printing of the same Card. The term comes from Magic databases.
- **Oracle name:** the base card name shared by all printings, without a variant suffix. Mentions, `@` search and decklists match on it.
- **Cleaned text:** a card's rules text after ingestion cleanup: icon shortcodes (such as `:rb_energy_1:`) rewritten as words and keyword brackets stripped. Used for retrieval and prompts. The **raw text** is kept alongside it.
- **Card snapshot:** the committed copy of Rifthunt's bulk card data, with its fetched date.

## Decks

- **Decklist:** a saved list of cards in sectioned plain text, parsed deterministically in code.
- **Deck section:** one block of a Decklist: Legend, Champion, MainDeck, Battlefields, Runes or Sideboard.
- **Import validation:** resolving each Decklist line to a real Card and running structural checks. Problems are warnings and never block the import.

## Knowledge sources

- **Rules:** the official Riftbound rules document. Only the current version is kept, with its version and date.
- **FAQ:** an official Riot post-set FAQ. The only blog-type source.
- **Source:** where a chunk comes from: FAQ, card text or rules.
- **Source precedence:** FAQ > card text > rules when sources disagree. Between two FAQs, the newer wins.
- **Chunk:** a retrievable piece of a source. Rules are chunked by rule number and section, and keep the rule id and parent section as metadata. Every chunk carries its source type and date.
- **Ruling:** an answer to a question about how rules and cards interact, as given by the judge-style bot.

## Agent behavior

- **Citation:** a reference in an answer to the rule number or source that supports it.
- **Evidence grade:** the graph step that judges whether the retrieved chunks are strong enough to answer.
- **Abstain:** saying that evidence is weak, or asking a clarifying question, instead of guessing.
- **Corrective retry:** the single retry with a rewritten query when the evidence grade is weak.
- **`lookup_card`:** the LLM tool that reads a Card from our database. Each call is traced.

## Chat interface

- **Mention (`@`):** a user-picked Card or Deck in the composer, injected into the conversation context. Cards are injected with full text, Decks as card names only.
- **Card tag (`[[Card Name]]`):** the markup the model uses for a card in an answer. Only tags validated against the card database get hover previews.
- **Conversation / Message:** the stored chat history, kept in our own tables.

## Evaluation and observability

- **Golden set:** the hand-written set of about 30-50 rulings with expected rule numbers, run as a Langfuse dataset and experiment.
- **Trace:** the Langfuse record of one chat response. Its id is returned to the frontend so that feedback can be scored on it.
- **Feedback:** the thumbs up/down on a message, sent as a Langfuse score on that message's trace.
