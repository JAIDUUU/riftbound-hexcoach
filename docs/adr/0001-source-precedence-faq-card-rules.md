# 0001: Source precedence is FAQ > card text > rules

Status: accepted

## Context
The bot answers from three sources: the rules document, card text, and Riot's official post-set FAQs. They can disagree. The FAQs are published after each set and clarify or correct earlier material. Card text can override the general rules when a card contradicts them.

## Decision
When sources disagree the order is **FAQ > card text > rules**. If two FAQs conflict, the newer one wins. Every chunk carries its source type and date, and the precedence is stated in the prompt. The FAQs are the only blog-type source: no other blog posts are ingested.

Precedence is a conflict rule, not a ranking rule: retrieval orders results by relevance, `order_by_precedence` groups them by source class without reordering within a class, and the answerer applies "newer FAQ wins" only when two FAQs actually conflict, using the dates on the chunks. Date-sorting all FAQs up front would bury an older but more relevant ruling.

## Consequences
- Ingestion must record a source type and a date on every chunk.
- Citations always name the source. An FAQ-only answer needs no extra label.
- The golden set should include conflict cases between an FAQ, a card and a rule.
- Community rulings are out of scope (see [0006](0006-no-community-rulings.md)).
