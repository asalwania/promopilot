# Planning happens at a configurable as-of week

Every planning session and eval scenario has an **as-of week** that it treats as "today": sales history before it is visible to models and agents, and everything from it onward is future (inventory is the snapshot at the end of the week before). It defaults to the first week after the 104 generated history weeks. We rejected a single fixed clock because the eval suite needs scenarios in different seasons (Diwali, Pongal, Durga Puja, Christmas, off-season); a movable as-of week provides them without leaking future sales into training or planning.

## Consequences

- The generator produces the calendar (with holidays), competitor prices and true demand beyond the history end so windows after any as-of week can be planned and scored by the oracle.
- Every data-access call, model fit and inventory snapshot takes the as-of week explicitly; reading data at or after it outside `promopilot.evals` is a leakage bug.
- The **promo window** must lie entirely after the as-of week.
