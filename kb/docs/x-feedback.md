---
created: 2026-08-21
tags:
  - x
  - feedback
  - frontend
  - ios
  - taxonomy
---

# X feedback — up/down labels and down-reason chips

The reader's up/down labels on X tweets: the API + storage, the down-reason chip UI on
web and iOS, and the taxonomy decisions. These labels are the verdict's training set
(`kb/docs/x-verdict.md`); schema details are v7/v9 in `kb/docs/database.md`.

## Feedback API (Phase 3, 2026-07-25)

`POST /api/feedback {key, verdict}` / `DELETE /api/feedback/{key}`
(`routers/reading.py`, next to hide — same triple-keyed family) write `item_feedback`.
The envelope carries the current label back as `feedback`, joined live in `sources/x.py`
and, for saved records, batched in `records._saved_feedback` (deliberately NOT
snapshotted — the label keeps changing after the save). Web: `XFeedbackButtons` on the
card footer + `useFeedback`. The endpoints are source-generic like the table, but only X
joins the field today.

Phase 3 **only records the label** — nothing is hidden, ranked or filtered by it; that
is Phase 4's verdict, trained on exactly these labels (plus saved items as strong
positives), which is why followed-account tweets are markable even though they will
never get a verdict. iOS got the buttons in Phase 5 (2026-07-25) with the rest of the X
surfaces.

## Down-reason chips (2026-07-26, schema v9)

The thumbs-down asks *why*: `POST /api/feedback` takes an optional `reason` and the
envelope carries it back as the sibling field `feedback_reason` (**not** nested into
`feedback`: shipped iOS builds decode that as a bare string, and an object would fail
the whole page's decode on a binary users upgrade separately).

Two rules make it safe:

- A POST states the **whole** label — omitting the reason clears a stored one, so
  correcting a down-with-reason into an up cannot carry `ai_slop` onto a positive.
- The chip is **skippable at zero cost** — no pick is exactly the bag-level label we had
  before.

Web asks with an inline chip row under the card footer (`XFeedbackButtons`, transient —
it answers *this* click and never re-nags an already-labeled tweet); iOS asks with a
native `confirmationDialog` (the Chinese labels don't fit one phone-width row, and the
system sheet is already "tap one / Cancel to skip"). The picked reason is echoed only in
the detail pane, never on the card.

`FEEDBACK_REASONS` lives in `db.py` / `lib/sources.ts` / Kit's
`ItemFeedbackReason.offered`, plus the request schema's Literal in `types.py` — pinned
to `db.FEEDBACK_REASONS` by a test, because a one-sided edit means the endpoint accepts
and stores a label nothing can route. Why this exists — and why it was missing until
now — is the "Phase 3 补记" section of the X plan.

## `engagement_farming`「博眼球」(2026-07-27)

Joined the taxonomy as a constant-only change (`reason` is a nullable TEXT column, so no
migration and no schema bump). It is X's own platform-manipulation term for the
influencer-thread pattern — hook, FOMO, "save this 🔖", payoff parked in the replies so
an outbound link doesn't cost reach — and it is deliberately **not** a flavour of
`promo`: promo sells a thing (intent), this games interaction (largely lexical, so the
n-gram channel can learn it outright while `promo` needs the expensive LLM one).

The rejected alternatives are worth knowing, since the argument recurs: `clout` overlaps
`promo` semantically (clout chasing *is* self-promotion) and a chip the reader hesitates
over yields noisy labels; `content_farm` names an operation rather than an item, and
encodes a *quality* judgement that would misfire on the digest/summary accounts the user
likes — those are derivative too, and differ only in not baiting. Being a superset (rage
bait, poll bait, giveaways) is a feature: it reaches a trainable label count sooner,
which is the binding constraint.

The Chinese label started as the literal 「钓互动」 and became **「博眼球」** the same
day (display-string only — the value, its scope and the stored labels are untouched): a
chip is read mid-scroll, so an idiomatic phrase gets pressed while a translated one gets
skipped. Known trade-off: 博眼球 leans toward the hook/clickbait flavour and reads less
obviously right on a giveaway or a poll, which the value still covers. Full reasoning:
`kb/notes/2026-07-27-engagement-farming-chip.md`.
