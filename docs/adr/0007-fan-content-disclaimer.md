# 0007: Fan-content and "not an official judge" disclaimers

Status: proposed. The Riot policy wording is **not verified**.

## Context
HexCoach uses Riftbound card names, text and images, and rules content owned by Riot Games. Riot has a policy for fan-made content, and Rifthunt describes its own data as unofficial Fan Content under it. We have not read the policy ourselves, so we do not know the exact wording required or what it permits. The bot is also not an official judge.

## Decision
- Add Riot's required fan-content disclaimer to the README and to the chat footer once its exact wording is verified from the official policy.
- Show a "not an official judge" disclaimer in the chat footer, the README and the empty state. It is not appended to every answer.
- The bot has no features that play the game. It only helps players.

## Consequences
- Verifying Riot's policy is a blocker before the public demo.
- The policy may constrain what we can commit to the repo, hotlink or show, and this ADR must be updated if it does.
