# curation/

One file: `featured.json`. Which plugins the console puts in front of somebody who opens the store,
and in what order.

**This is editorial, and it is the one thing in this repository that is.** Everything else here is a
claim that had to survive a check — a digest against bytes, a signature against a pinned key, a
verification against a document at a URL derived from the publisher's own id. Featuring survives no
check, because there is nothing to check: nobody looked at the code, nobody tested it on your
hardware, nobody confirmed anything about whoever wrote it. Somebody decided it was worth showing
you first.

So it must never be rendered as, beside, or in place of a **publisher tier**. `official`, `verified`
and `unverified` say who published something and are refused unless that can be shown.
**Featured says we put it in the window. It never says anybody checked it.** A console that draws
the two as two kinds of badge has turned an opinion into a check, which is the one lie in this
registry somebody would act on.

## Who may write it

**Maintainers, never a publisher** — the same authority `verification/` has, enforced the same two
ways: a pull request that touches this directory needs the maintainer-only `curation` label, and
[CODEOWNERS](../.github/CODEOWNERS) puts a maintainer's review on the path. The label is what CI can
see and fail on; CODEOWNERS is what branch protection enforces. Neither is the other's substitute.

**A plugin cannot feature itself, structurally rather than by review.** There is no `featured` field
in a submission and `plugins/<id>/plugin.json` is `additionalProperties: false`, so writing one is a
schema failure rather than a field somebody has to notice; a plugin directory may hold only
`plugin.json`, `README.md` and `icon.png`, so a `featured.json` dropped in beside a manifest is
refused as an unexpected file; and this file is not one a submission can reach. The only diff that
features anything is one a maintainer both wrote and labelled.

## The file

```json
{
  "$schema": "../schema/featured.schema.json",
  "schema": 1,
  "updatedAt": "2026-08-18",
  "spotlight": {
    "plugin": "com.acme.lamp",
    "blurb": "Speaks to Acme's bridge over the local network, so the lamps keep working with the internet unplugged.",
    "since": "2026-08-18"
  },
  "featured": [
    { "plugin": "com.acme.lamp", "note": "why this is on the list, for whoever reads it in a year" }
  ]
}
```

`spotlight` is its own field rather than the first row because the blurb is our prose about somebody
else's binary, which is a heavier thing to publish than a place in an order — so the schema requires
it, and you cannot spotlight something without saying why. A plugin may be spotlit **or** featured
and never both; CI refuses the overlap rather than resolving it quietly. `note` is for us and is
never published.

One ordered file rather than a record per plugin, because **the order is the editorial content**. In
a rank field two pull requests can each move something to the top and merge cleanly into a list that
is now wrong, with no conflict for anybody to resolve. Here a reordering reads as a reordering.

## What CI refuses

| | |
|---|---|
| `CURATION_UNAPPROVED` | the diff has no `curation` label |
| `CURATION_UNKNOWN_PLUGIN` | a featured id with no `plugins/<id>/` — a window pointing at nothing |
| `CURATION_NOTHING_OFFERED` | every version withdrawn, so following it offers nothing to install |
| `CURATION_DUPLICATE` | the same plugin twice, or spotlit and listed |
| `CURATION_TOO_MANY` | more than `policy.MAX_FEATURED`; a window with everything in it distinguishes nothing |

What CI cannot decide is whether this is a good plugin to feature. That is the judgement, and the
label is somebody asserting they made it.

## Where it ends up

`index/catalog.json`, and nowhere else. The per-plugin document a hub installs from has no field for
it and refuses one, so **a hub that never reads the catalogue installs exactly what it would have
installed anyway.** Featuring is decoration on browse; it is never on a path anything depends on.
See [docs/featured.md](../docs/featured.md) and [docs/index-format.md](../docs/index-format.md).

Empty for now: nothing is published here yet, so there is nothing to put in a window. A missing file
is "nothing is featured" and is not an error.
