# Featured — the shop window, and the one thing it is not

Somewhere on the store screen a few plugins get shown first. This page is about who decides that,
where the decision is written down, and why it is kept as far as possible from everything else in
this repository.

**Featured says we put it in the window. It never says anybody checked it.**

That sentence is the whole page. Everything below is why it needs its own file, its own label, its
own place in the feed, and a schema that cannot spell a tier.

---

## Editorial, not evidential

Every other claim in this registry had to survive contact with the world:

| | what it asserts | what refuses it |
|---|---|---|
| a digest | these are the bytes we listed | SHA-256 over what was actually downloaded |
| a signature | the publisher who published version 1 published this one | a key pinned on first publication |
| `verified` | this publisher controls the name their id claims | a document at a URL **derived from that id**, re-read weekly |
| `official` | we published this | a tuple in our own source, which no diff of yours can reach |

**Featuring asserts none of that, and it never can.** Nobody read the code. Nobody ran it on your
hardware. Nobody confirmed anything about whoever wrote it that was not already confirmed — a
featured plugin from an `unverified` publisher is still from an `unverified` publisher, and the store
has to keep saying so beside it.

What featuring is, is an *opinion*: somebody here thought this was worth showing you first. That is a
real and useful thing for a store to have, and it is also the kind of thing that quietly turns into
an endorsement if it is drawn next to a check and in the same visual language.

So the rules are shaped for what it is:

- there is nothing to fetch, and `tools/registry/curation.py` never touches the network;
- it fails **closed to nothing** rather than closed to a lower value — an entry that cannot be
  resolved is simply not featured, which leaves a plugin exactly where every plugin starts;
- and it is published to the browse document and to nothing else.

---

## Where it lives, and where it does not

The source is one file, `curation/featured.json`, maintainer-owned. It is published into
`index/catalog.json` as a `featured` block, and **that is the only document it appears in.**

```
index/catalog.json          browse and search — carries the window
index/plugins/<id>.json     what a hub fetches to INSTALL — has nowhere to put one
```

That split already existed for a different reason ([index-format.md](index-format.md)): the install
document is kept small because *"a document that grows with every release is a document that
eventually fails to parse on the oldest box in the field"*, and the catalogue is allowed to grow
because *"no install or update path may depend on it"*.

Putting the window on the second and never the first is what makes this true as a property of the
file layout rather than as a promise in a paragraph:

> **A hub that never sees the window installs exactly what it would have installed anyway.**

A hub browsing from a cache, a hub whose feed is unreachable, a hub installing from a link with no
registry involved at all — every one of them gets the same plugin, the same digest and the same
signature check. There is no version of this that becomes load-bearing later, because the install
document is `additionalProperties: false` and has no field to grow.

**And in particular: nothing about featuring is served by the cloud.** The window is signed static
data in the same document the browse list already comes from, so it needs no service of ours to be
read. This is deliberately the *opposite* choice from something like a rating, which changes
constantly and therefore cannot be a field in a signed document that is regenerated on merge. A
rating is a live number; a window is an editorial decision that changes on the scale of weeks, and
the cheapest honest place for it is the file everything else is already fetching.

---

## Who may write it

Maintainers, and structurally rather than by review. There are three independent guards and they
fail in three different places:

1. **A submission has no field for it.** `plugins/<id>/plugin.json` is `additionalProperties: false`
   and has no `featured`, so writing one is `SCHEMA_INVALID` — a refusal, not a field somebody has to
   notice and ignore. Same for `spotlight`, and same for the third spelling nobody has thought of,
   because the schema is closed rather than carrying a list of forbidden names.
2. **A plugin directory has no room for it.** Only `plugin.json`, `README.md` and `icon.png` are
   allowed inside one, so a `featured.json` dropped in beside a manifest is `LAYOUT_UNEXPECTED_FILE`.
3. **The list itself needs a maintainer.** A pull request touching `curation/` needs the
   maintainer-only `curation` label, checked by the validator as `CURATION_UNAPPROVED`, and
   [CODEOWNERS](../.github/CODEOWNERS) puts a maintainer's review on the path. The label is what CI
   can see and fail on; CODEOWNERS is what branch protection enforces. **Neither is the other's
   substitute** — the same pair, for the same reasons, as `verification/`.

So the only diff that features a plugin is one a maintainer both wrote and labelled. A submitter can
open any pull request they like and there is no field in it that reaches this file.

---

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
    { "plugin": "com.other.thermostat", "note": "the only thermostat published so far", "since": "2026-08-18" }
  ]
}
```

**One ordered file rather than a record per plugin**, because the order *is* the editorial content.
Rank fields merge cleanly and wrongly: two pull requests each move something to the top, git finds no
conflict, and the list that lands is one nobody wrote. In one file a reordering reads as a
reordering in the diff, which is the thing a reviewer is being asked to approve.

**`spotlight` is its own field rather than the first row**, because a blurb is our prose about
somebody else's binary — a heavier thing to publish than a place in an order. The schema requires it,
so you cannot spotlight something without saying why. A plugin may be spotlit *or* featured, never
both; CI refuses the overlap rather than resolving it, because two rows for one plugin means somebody
edited the list without reading it and that is the fault worth surfacing.

**`note` is never published.** It is how we remember why something is on the list. Publishing it
would put a second piece of our unreviewed voice beside a stranger's plugin; the spotlight's blurb is
the one line written to be read.

### What the blurb may say

It may describe what a plugin does and why somebody might want it. It may not say or imply that it
is safe, audited, tested or endorsed — none of which happened. The README's table of what this
registry can honestly tell you before you install is unchanged by anything on this page, and a blurb
that reads like a line in that table is a blurb to rewrite.

---

## What CI refuses

| code | |
|---|---|
| `CURATION_UNAPPROVED` | the diff has no `curation` label |
| `CURATION_UNKNOWN_PLUGIN` | a featured id with no `plugins/<id>/` |
| `CURATION_NOTHING_OFFERED` | every version withdrawn — a window with an empty box in it |
| `CURATION_DUPLICATE` | the same plugin twice, or spotlit and listed |
| `CURATION_TOO_MANY` | more than `policy.MAX_FEATURED`, which is 12 |

The last one is worth a sentence. A window with everything in it distinguishes nothing: past some
length featuring stops being a decision and becomes a second copy of the catalogue in an order nobody
chose. Twelve is a browse row on a phone and a grid on a console.

**What CI cannot decide is whether a plugin deserves to be featured.** That is the judgement, and the
label is somebody asserting they made it. This is the same split the verification page draws — CI
proves control of a name and a person decides whether that name is who it sounds like — and it is
wider here, because on this page CI proves nothing about the plugin at all.

---

## Editing it from the cloud console

The reMaestro cloud service has an admin screen that composes changes to this file and **opens a pull
request** against this repository. It has a fine-grained token scoped to this repository and to
Contents and Pull requests only, and it has no way to push to `main`.

That is the entire design: an edit from the console arrives as a diff, CI runs on it, the `curation`
label has to be applied by a person, and a person merges it. Which means the console is a
*convenience over the pull request*, not a way around it — everything on this page is still true
about a change that came from a web form, and there is no path by which a store admin's mistake
becomes a published feed without anybody looking.

If the console cannot open the pull request — no token, rate limited, a branch already open for the
same change, or the base having moved — it says which of those it was and changes nothing. See the
hub repository's `docs/cloud.md`.
