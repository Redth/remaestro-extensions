"""Publisher tiers: where they come from, and the one thing they are allowed to mean.

**A tier says who a publisher is. It never says a plugin is safe.** Under the model reMaestro chose,
installing a plugin runs an arbitrary binary with the hub's own privileges, and provenance is the
only control that exists — so a badge that reads as a safety claim is not a small wording problem, it
is the one sentence in this repository somebody would act on and be wrong about. Every place a tier
is rendered or documented carries what it does and does not assert.

Three tiers and three different authorities, which is the point:

**official** — published by us. Decidable by us, and it lives in `policy.OFFICIAL_PUBLISHERS`: a
tuple in our own source, not a field, not a label, not anything a submission can carry. There is no
diff a stranger can open that puts them in it.

**verified** — a maintainer checked that this publisher controls the name their id claims, and the
check is recorded in `verification/<id>.json`. That file is written by a maintainer and never by its
subject, which is the whole reason it is not a field in `publishers/<id>.json` — that document is
submitted by the publisher it describes, so a tier in it would be self-asserted by construction.

**unverified** — everybody else, and it is the default in the strongest sense: it is what you get
from a missing file, a withdrawn verification, a record that no longer resolves, and anything this
module cannot make sense of. Nothing fails open into a better tier.

What CI can decide and what it cannot, stated here because it is the part that gets overclaimed:
CI can decide that the evidence resolves, that it sits at the URL the id implies and nowhere else,
and that it names this publisher. **A person has to decide that whoever controls that name is the
entity the record's name suggests**, and that the name is not deliberately confusable with somebody
else's. Control of a name is checkable. Identity is not, and nothing here pretends otherwise.
"""

from __future__ import annotations

import json
import os

from . import fetch, policy


def evidence_url(publisher_id: str) -> str:
    """Where this publisher's evidence must live, derived from their id and from nothing else.

    Reverse the reverse-DNS: `com.acme` claims `acme.com`, so that is where the claim is checked.
    Deriving it rather than reading it out of the record is the property that makes the whole check
    worth anything — an evidence URL a submitter supplies is a check of whatever they chose to serve.
    """

    host = ".".join(reversed(publisher_id.split(".")))
    return f"https://{host}{policy.WELL_KNOWN_PATH}"


def proves(document: str, publisher_id: str) -> bool:
    """Whether that document carries the line naming this publisher.

    Line-oriented and split on the first `=`, so a hand-edited file with spaces around it still
    works, and a page that merely mentions the id in a sentence still does not.
    """

    for line in document.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == policy.WELL_KNOWN_KEY and value.strip() == publisher_id:
            return True
    return False


def why_missing(publisher_id: str) -> str:
    """The two ordinary reasons that document is not there, named rather than shrugged at.

    A 404 has one appearance and two causes, and they need different actions: the file was never
    published, or it was published to a GitHub Pages site running Jekyll — which **excludes
    dot-directories from its output**, so `.well-known/` is in the repository and not on the site.
    Measured, on 2026-08-18: `docs.github.com/.well-known/security.txt` and the same path on
    `pages.github.com` both answer 404, and a Pages site that does carry a dot-file carries it
    because `.nojekyll` is committed beside it.

    That failure is invisible from the publisher's side — the file is in their repository, they can
    see it on github.com — so a refusal that says only "404" sends them to look at the one thing that
    is fine. This is `#267`'s rule about the four refusals, applied one level down: an event with two
    causes gets both of them named.
    """

    host = ".".join(reversed(publisher_id.split(".")))
    if host.endswith(".github.io"):
        return ("Two things usually cause this on a GitHub Pages site: the file was never published, or it "
                "was published under Jekyll, which drops dot-directories from the built site — so "
                "`.well-known/` is in the repository and not on the site. Commit an empty `.nojekyll` at "
                "the repository root to turn that off.")
    return ("Two things usually cause this: the file was never published, or the host serves it only "
            "under a redirect or an authentication wall that a plain GET does not pass.")


def records(repo: str) -> dict[str, dict]:
    """Every verification record, by publisher id.

    A missing directory is no verifications rather than an error: a registry with nobody verified is
    the ordinary state and is what this one is in today. Unreadable records are skipped here and
    failed by the validator — this loader is also the index generator's, and an index that refuses
    to build over a malformed file would take the whole feed down for one publisher.
    """

    directory = os.path.join(repo, "verification")
    if not os.path.isdir(directory):
        return {}

    found: dict[str, dict] = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        # Read here rather than through validate.load_json, which would make this module and the
        # validator import each other. The validator is the thing that reports a malformed record;
        # what this needs is only to not offer one as a tier.
        try:
            with open(os.path.join(directory, name), "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        publisher = document.get("publisher")
        if isinstance(publisher, str) and publisher == name[: -len(".json")]:
            found[publisher] = document
    return found


def active(record: dict | None) -> bool:
    return bool(record) and record.get("status") == "active"


def tier_of(publisher_id: str, found: dict[str, dict]) -> str:
    """The tier this publisher is in, resolved in the order the three authorities rank.

    Official first, because it is the one answer that needs nothing fetched. Then an active
    verification. Then unverified, which is every other case including all the broken ones.
    """

    if publisher_id in policy.OFFICIAL_PUBLISHERS:
        return "official"
    if active(found.get(publisher_id)):
        return "verified"
    return "unverified"


def published(record: dict | None) -> dict | None:
    """What the index tells a hub about a verification, or None.

    Deliberately not the whole record: `checkedBy` and `note` are how *we* audit this and are of no
    use to a console, and publishing a maintainer's name beside somebody else's plugin invites it to
    be read as an endorsement by that person. What a hub gets is what was checked, where, and when —
    enough for a console to say *"the registry checked control of acme.com on 18 August 2026"*, which
    is a fact somebody can act on, rather than a tick, which is not.
    """

    if not active(record):
        return None
    assert record is not None
    return {
        "method": record["method"],
        "evidence": record["evidence"],
        "checkedAt": record["checkedAt"],
    }


def check_evidence(publisher_id: str, record: dict, origins: fetch.OriginMap) -> tuple[str, str] | None:
    """Fetch the evidence and read it. None when it proves what it claims, else (code, message).

    Returned rather than reported so the validator owns every finding it emits, and so this can be
    called from the audit without a report object.
    """

    expected = evidence_url(publisher_id)
    if record["evidence"] != expected:
        return ("VERIFICATION_EVIDENCE_MISPLACED",
                f"the evidence is at {record['evidence']}, and the only place it counts for "
                f"{publisher_id!r} is {expected}. The location is derived from the publisher id and never "
                "taken from the record: a URL somebody can choose is a check of whatever they chose to serve")

    document, problem = fetch.text(expected, origins, policy.MAX_EVIDENCE_BYTES)
    if problem is not None:
        return ("VERIFICATION_EVIDENCE_UNRESOLVED",
                f"{problem}. A verification whose evidence cannot be read is not a verification; it is a "
                f"claim we made once and can no longer stand behind. {why_missing(publisher_id)}")

    if not proves(document or "", publisher_id):
        return ("VERIFICATION_EVIDENCE_UNPROVEN",
                f"{expected} does not carry the line '{policy.WELL_KNOWN_KEY}={publisher_id}'. Whoever "
                "controls that name has not said this publisher is theirs")

    return None
