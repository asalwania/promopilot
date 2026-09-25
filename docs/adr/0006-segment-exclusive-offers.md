# Segment-exclusive offers, plus an "All customers" open promotion

A plan line's **target segment** is either one behavioural segment, meaning a **segment-exclusive offer** (e.g. a loyalty coupon) that other segments don't receive, or **All customers**, meaning an open shelf promotion. We rejected "open offer, targeted communication", where everyone gets the price and the segment only steers marketing, because targeting would then carry no real economics; with exclusive offers, discount funding and uplift come only from the targeted segment's units, so choosing a segment is a genuine trade-off between reach and discount spend (SPEC F-03 AC2).

## Consequences

- The synthetic generator, demand model, simulator and oracle must all model demand per segment, with a segment-exclusive promotion changing only that segment's effective price.
- Segments remain behavioural (Value Seekers, Families, Premium, Young Urban); targeting on protected attributes is out of scope by design.
