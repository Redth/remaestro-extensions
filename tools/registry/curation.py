"""Featured plugins: who may say so, and the one thing featuring is allowed to mean.

**Featuring is editorial. A tier is evidential. Keeping those apart is the whole of this module.**

`verified` records something that was *checked*: a maintainer read a document at a URL derived from
the publisher's own id, and CI refuses the record if that document stops saying what it said.
`official` records something that is *decidable by us*, out of a tuple in `policy.py`. Both are
claims about **who a publisher is**, and both are refused unless the thing they assert can be shown.

Featuring asserts nothing of the kind. Nobody checked anything; somebody *decided* something — that
this is worth putting in front of a person who opened the store. It is a shop window, and a shop
window is not a certificate. So the rules here are shaped differently on purpose:

* there is no evidence to fetch, and this module never touches the network;
* it fails **closed to nothing** rather than closed to a lower tier — an unresolvable entry is simply
  not featured, which leaves a plugin exactly where every plugin starts;
* and the index carries it **only in `catalog.json`**, never in the per-plugin install document.

That last one is the load-bearing one. `catalog.json` is browse-and-search and *"no install or
update path may depend on it"*; `plugins/<id>.json` is what a hub fetches to install. Putting
featuring in the browse document and nowhere else makes *"featured is decoration, and a hub that
never sees it still installs everything"* a property of the file layout rather than a promise in a
paragraph. There is no version of this that can quietly become a dependency, because the document an
install reads has no field to put it in and `additionalProperties: false` refuses one.

**What stops a plugin featuring itself** is the same shape that stops it claiming a tier, and it is
structural in three independent places rather than reviewed in one:

1. `plugins/<id>/plugin.json` is `additionalProperties: false` with no `featured` field, so writing
   one is `SCHEMA_INVALID` rather than a field somebody has to notice and ignore.
2. `check_layout` allows exactly `plugin.json`, `README.md` and `icon.png` inside a plugin
   directory, so a `featured.json` smuggled in beside a manifest is `LAYOUT_UNEXPECTED_FILE`.
3. The list lives in `curation/featured.json`, which needs the maintainer-only `curation` label and
   is covered by CODEOWNERS — the two guards `verification/` already has, enforced in two different
   places, neither a substitute for the other.

So the only diff that features a plugin is one a maintainer both wrote and labelled. A submitter can
open any pull request they like and there is no field in it that reaches this file.
"""

from __future__ import annotations

import json
import os

from . import policy

#: Where the list lives, relative to the repository root. One file, not a record per plugin —
#: see `load` for why.
PATH = os.path.join("curation", "featured.json")

#: The directory, for the layout check.
DIRECTORY = "curation"


def load(repo: str) -> dict | None:
    """The featured list, or None when there is not one.

    **A missing file is "nothing is featured", which is the ordinary state and is what this registry
    is in today.** Not an error, and not something to invent a default for: a store with an empty
    window is a store, and every plugin is reachable by search either way.

    Unreadable is treated the same as missing *here* and failed by the validator, for the reason
    `verification.records` gives: this loader is also the index generator's, and a feed that refuses
    to build over one malformed editorial file would take every plugin down to protect a shop window.

    One file rather than `curation/<id>.json` per plugin, deliberately. **The order is the editorial
    content** — "which of these does somebody see first" is most of what featuring decides — and an
    order spread across a record per plugin would have to live in a rank field, where two pull
    requests can each move something to the top and merge cleanly into a list that is now wrong with
    no conflict for anybody to resolve. In one file a reordering reads as a reordering in the diff.
    """

    path = os.path.join(repo, PATH)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def entries(document: dict | None) -> list[dict]:
    """Every row of the ordered list, spotlight excluded. Anything unrecognisable is dropped."""

    if not isinstance(document, dict):
        return []
    rows = document.get("featured")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("plugin"), str)]


def spotlight(document: dict | None) -> dict | None:
    """The one plugin with a sentence beside it, or None.

    Its own field rather than the head of the list because a blurb is our prose about somebody
    else's binary, which is a heavier thing to publish than a position in an order. The schema
    requires it, so there is no way to spotlight something without saying why.
    """

    if not isinstance(document, dict):
        return None
    one = document.get("spotlight")
    if not isinstance(one, dict) or not isinstance(one.get("plugin"), str):
        return None
    if not isinstance(one.get("blurb"), str) or not one["blurb"].strip():
        return None
    return one


def published(document: dict | None, known: set[str]) -> dict | None:
    """What the browse catalogue is told, or None when nothing is featured.

    `known` is the set of plugin ids the index actually built a row for, and every id is filtered
    through it here as well as being refused by the validator. Belt and braces on purpose and not
    redundantly: the validator runs on a pull request and this runs on `main`, and the one thing a
    generator must never do is emit a document naming a plugin the same document does not contain.
    A console following that id would 404 against our own feed.

    Deliberately **not** the whole file. `note` is how we remember why something is on the list and
    is nobody else's business; publishing it would put a second piece of our unreviewed voice beside
    a stranger's plugin. What ships is the order, and the spotlight's blurb, which is the one line
    written to be read.
    """

    order = []
    seen: set[str] = set()
    for row in entries(document):
        plugin = row["plugin"]
        if plugin in known and plugin not in seen:
            seen.add(plugin)
            order.append(plugin)

    one = spotlight(document)
    hero = None
    if one is not None and one["plugin"] in known:
        hero = {"id": one["plugin"], "blurb": one["blurb"].strip()}

    if hero is None and not order:
        return None

    block: dict = {"plugins": order}
    if hero is not None:
        block["spotlight"] = hero
    return block


def installable(plugin: dict) -> bool:
    """Whether a submission offers a version somebody could actually install.

    Featuring something whose every version has been withdrawn is a shop window with an empty box in
    it, and the person who clicks it gets a page offering them nothing. Read off the submission
    rather than off the built index so the validator can say it on a pull request, before the index
    that would have shown the hole is ever generated.
    """

    versions = plugin.get("versions")
    if not isinstance(versions, list):
        return False
    return any(isinstance(v, dict) and "withdrawn" not in v for v in versions)


def too_many(document: dict | None) -> int | None:
    """How many rows there are, when that is more than a window can hold. None when it is fine.

    A window with everything in it is a window with nothing in it: past a certain length, featuring
    stops distinguishing anything and becomes a second copy of the catalogue in an arbitrary order.
    The number is in `policy.py` with every other one, so moving it is a one-line diff a reviewer
    reads rather than a constant buried in a check.
    """

    count = len(entries(document))
    return count if count > policy.MAX_FEATURED else None
