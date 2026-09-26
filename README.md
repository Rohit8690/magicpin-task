# Magicpin AI Challenge — Vera

## Approach

This submission implements a context-grounded merchant assistant without requiring an external API key.

The composer uses four pieces of context:
- category: voice, peer statistics, digest, offers and category vocabulary
- merchant: identity, performance, offers, signals and subscription
- trigger: why the message should be sent now
- customer: optional customer relationship, language preference and consent context

The message router selects a trigger-specific composition strategy for research,
regulation, performance, peer benchmark, offer/campaign, subscription, trend and
customer-recall flows.

The implementation deliberately avoids inventing facts. When a required fact is
not present, it falls back to an available concrete context value instead of
fabricating a number, offer, citation or competitor.

For multi-turn conversations, the bot:
- detects likely canned/auto replies
- switches to action mode after explicit acceptance
- exits on explicit opt-out/not-interested messages
- backs off when the merchant asks for time
- keeps responses bounded when the context does not contain the requested detail

## Files

- `bot.py` — FastAPI bot with `/v1/context`, `/v1/tick`, `/v1/reply`,
  `/v1/healthz`, `/v1/metadata`
- `generate_submission.py` — creates `submission.jsonl` from supplied contexts
- `requirements.txt` — runtime dependencies
- `README.md` — this document

Before submitting, replace the placeholder contact email in `bot.py` and metadata
with the actual contact email required by the challenge portal.
