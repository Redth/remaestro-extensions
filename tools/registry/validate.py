"""The gate a submission passes before a human looks at it.

The point of this file is stated once and then assumed everywhere below: **a reviewer should be
judging intent, not syntax.** Anything a machine can decide — does the schema hold, does the URL
answer, do the bytes hash to what was claimed, was this signed by the key this publisher has been
pinned to since their first plugin — is decided here, and a person never spends attention on it.

What it deliberately does not do is say anything about whether a plugin is safe. It cannot. See
README.md, which says so where a submitter and a user will both read it.

Exit code is the verdict: 0 clean, 1 something failed, 2 the validator itself could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from typing import Any

from . import curation, fetch, gitref, policy, verification

REPO_ROOT_MARKERS = ("schema", "plugins", "publishers")


# ---------------------------------------------------------------------------------------------
# findings


@dataclass(frozen=True)
class Finding:
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}  {self.where}\n    {self.message}"


class Report:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.notes: list[str] = []

    def fail(self, code: str, where: str, message: str) -> None:
        self.findings.append(Finding(code, where, message))

    def note(self, message: str) -> None:
        self.notes.append(message)

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


# ---------------------------------------------------------------------------------------------
# loading


def load_json(path: str) -> tuple[Any | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, "the file is not there"
    except UnicodeDecodeError as error:
        return None, f"the file is not UTF-8: {error}"
    except json.JSONDecodeError as error:
        return None, f"the file is not readable JSON: {error}"


def schema_validator(repo: str, name: str):
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - the workflow installs it
        print("jsonschema is not installed. pip install -r tools/requirements.txt", file=sys.stderr)
        raise SystemExit(2)

    path = os.path.join(repo, "schema", name)
    document, problem = load_json(path)
    if problem is not None:
        print(f"the registry's own schema {name} could not be read: {problem}", file=sys.stderr)
        raise SystemExit(2)
    jsonschema.Draft202012Validator.check_schema(document)
    return jsonschema.Draft202012Validator(document, format_checker=jsonschema.FormatChecker())


def check_schema(report: Report, validator, document: Any, where: str) -> bool:
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        report.fail("SCHEMA_INVALID", where, f"{location}: {error.message}")
    return not errors


# ---------------------------------------------------------------------------------------------
# layout and identity


def check_layout(report: Report, repo: str) -> tuple[list[str], list[str], list[str]]:
    """Returns (publisher files, plugin directories, verification files). Anything unexpected in any
    of the three trees is a failure rather than a shrug — a stray file in `plugins/` is either a
    mistake or an attempt to make one look ordinary."""

    publishers_dir = os.path.join(repo, "publishers")
    plugins_dir = os.path.join(repo, "plugins")
    verification_dir = os.path.join(repo, "verification")
    publisher_files: list[str] = []
    plugin_dirs: list[str] = []
    verification_files: list[str] = []

    for entry in sorted(os.listdir(publishers_dir)) if os.path.isdir(publishers_dir) else []:
        if entry in ("README.md", ".gitkeep"):
            continue
        full = os.path.join(publishers_dir, entry)
        if not os.path.isfile(full) or not entry.endswith(".json"):
            report.fail("LAYOUT_UNEXPECTED_FILE", f"publishers/{entry}",
                        "publishers/ holds one <publisher-id>.json per publisher and nothing else")
            continue
        publisher_files.append(entry)

    for entry in sorted(os.listdir(plugins_dir)) if os.path.isdir(plugins_dir) else []:
        if entry in ("README.md", ".gitkeep"):
            continue
        full = os.path.join(plugins_dir, entry)
        if not os.path.isdir(full):
            report.fail("LAYOUT_UNEXPECTED_FILE", f"plugins/{entry}",
                        "plugins/ holds one directory per plugin and nothing else")
            continue
        contents = sorted(os.listdir(full))
        if "plugin.json" not in contents:
            report.fail("LAYOUT_MISSING_MANIFEST", f"plugins/{entry}",
                        "a plugin directory must contain plugin.json")
            continue
        for item in contents:
            if item not in ("plugin.json", "README.md", "icon.png"):
                report.fail("LAYOUT_UNEXPECTED_FILE", f"plugins/{entry}/{item}",
                            "a plugin directory may contain plugin.json, README.md and icon.png only. "
                            "Artifacts live in the publisher's own storage; the registry carries a URL "
                            "and a digest, never the bytes")
        plugin_dirs.append(entry)

    # A missing verification/ is "nobody is verified", which is the registry's state today and is not
    # an error. What is an error is a stray file in it: this directory is the one place a tier comes
    # from, so anything in it that is not a record is either a mistake or something shaped to be
    # mistaken for one.
    for entry in sorted(os.listdir(verification_dir)) if os.path.isdir(verification_dir) else []:
        if entry in ("README.md", ".gitkeep"):
            continue
        full = os.path.join(verification_dir, entry)
        if not os.path.isfile(full) or not entry.endswith(".json"):
            report.fail("LAYOUT_UNEXPECTED_FILE", f"verification/{entry}",
                        "verification/ holds one <publisher-id>.json per verified publisher and nothing else")
            continue
        verification_files.append(entry)

    # Same rule again for the editorial list, and it is doing more work than it looks like. `curation/`
    # holds exactly one file; a second one is either somebody splitting the list — which would put the
    # order back into a rank field, the thing having one file avoids — or a file placed here to be
    # mistaken for it.
    curation_dir = os.path.join(repo, curation.DIRECTORY)
    for entry in sorted(os.listdir(curation_dir)) if os.path.isdir(curation_dir) else []:
        if entry in ("README.md", ".gitkeep", "featured.json"):
            continue
        report.fail("LAYOUT_UNEXPECTED_FILE", f"{curation.DIRECTORY}/{entry}",
                    f"{curation.DIRECTORY}/ holds featured.json and nothing else. The featured list is one "
                    "ordered file on purpose: the order is the editorial content, and an order split across "
                    "several files is a rank field two pull requests can each win")

    return publisher_files, plugin_dirs, verification_files


# ---------------------------------------------------------------------------------------------
# publishers


def check_publishers(report: Report, repo: str, files: list[str], validator,
                     base_ref: str | None, allow_rotation: bool) -> dict[str, dict]:
    publishers: dict[str, dict] = {}
    seen_lower: dict[str, str] = {}

    for name in files:
        path = os.path.join(repo, "publishers", name)
        where = f"publishers/{name}"
        document, problem = load_json(path)
        if problem is not None:
            report.fail("SCHEMA_INVALID", where, problem)
            continue
        if not check_schema(report, validator, document, where):
            continue

        expected_id = name[:-len(".json")]
        if document["id"] != expected_id:
            report.fail("PUBLISHER_ID_MISMATCH", where,
                        f"the record says id {document['id']!r} but the file is named {expected_id!r}. "
                        "A publisher id is the file name so that two records can never claim one identity")
            continue

        lower = expected_id.lower()
        if lower in seen_lower:
            report.fail("ID_DUPLICATE", where,
                        f"publisher id collides with {seen_lower[lower]} once case is ignored")
            continue
        seen_lower[lower] = where

        key_ids = [key["id"] for key in document["keys"]]
        if len(set(key_ids)) != len(key_ids):
            report.fail("KEY_DUPLICATE", where, "two keys share an id, so a signature cannot say which one made it")
            continue

        if base_ref is not None:
            previous = gitref.read_json_at(repo, base_ref, f"publishers/{name}")
            if previous is not None:
                _check_keys_pinned(report, where, previous, document, allow_rotation)

        publishers[expected_id] = document

    return publishers


def _check_keys_pinned(report: Report, where: str, previous: dict, current: dict, allow_rotation: bool) -> None:
    """The pinning rule, and it is the one that makes an index signing key tolerable.

    An index compromise can change *which* of a publisher's versions is offered. It cannot change
    *who* published a plugin, because that answer is here, in a file whose history is public, and
    a change to it is a diff a person had to approve.
    """

    before = {key["id"]: key for key in previous.get("keys", [])}
    after = {key["id"]: key for key in current.get("keys", [])}

    for key_id, old in before.items():
        if key_id not in after:
            report.fail("KEY_MUTATED", where,
                        f"key {key_id!r} was removed. A key is retired by setting status to 'revoked', "
                        "never by deleting it — the history is what a hub's warning is made of")
            continue
        new = after[key_id]
        for field in ("algorithm", "publicKey", "addedAt"):
            if old.get(field) != new.get(field):
                report.fail("KEY_MUTATED", where,
                            f"key {key_id!r} had its {field} changed. Pinned key material is append-only; "
                            "publish a new key id instead")
        if old.get("status") == "revoked" and new.get("status") == "active":
            report.fail("KEY_MUTATED", where,
                        f"key {key_id!r} was un-revoked. Revocation is one-way; issue a new key id")

    added = [key_id for key_id in after if key_id not in before]
    if added and not allow_rotation:
        report.fail("KEY_ROTATION_UNAPPROVED", where,
                    f"this pull request adds key(s) {', '.join(sorted(added))} to a publisher that already "
                    "has one. A rotation is a deliberate, human-reviewed operation: it needs the "
                    "'key-rotation' label, because an account takeover looks exactly like this")


# ---------------------------------------------------------------------------------------------
# verifications


def check_verifications(report: Report, repo: str, files: list[str], validator,
                        publishers: dict[str, dict], base_ref: str | None, origins: fetch.OriginMap,
                        offline: bool, allow_verification: bool, recheck_all: bool) -> dict[str, dict]:
    """The `verified` tier, and the two questions it has to survive.

    **Who wrote this?** A tier a publisher asserts is worthless, so the record does not live in any
    document a publisher submits — it lives here, and a pull request that touches this directory
    needs a maintainer's label, exactly as a key rotation does. That check and CODEOWNERS are two
    different guards on the same door: the label is what this validator can see, and branch
    protection requiring a code owner's review is what the repository can enforce. Neither is the
    other's substitute and the docs say which is which.

    **Is it still true?** The evidence is re-read rather than remembered. Its location is derived
    from the publisher id, so nothing here follows a URL somebody chose, and the weekly audit
    re-fetches every record — which is what notices a domain that has lapsed or changed hands since
    the day a person looked at it.
    """

    found: dict[str, dict] = {}

    for name in files:
        where = f"verification/{name}"
        document, problem = load_json(os.path.join(repo, "verification", name))
        if problem is not None:
            report.fail("SCHEMA_INVALID", where, problem)
            continue
        if not check_schema(report, validator, document, where):
            continue

        expected_id = name[: -len(".json")]
        if document["publisher"] != expected_id:
            report.fail("VERIFICATION_ID_MISMATCH", where,
                        f"the record verifies {document['publisher']!r} and the file is named "
                        f"{expected_id!r}. The file name is the publisher, so a record can never be about "
                        "one publisher while counting for another")
            continue

        if expected_id not in publishers:
            report.fail("PUBLISHER_UNKNOWN", where,
                        f"there is no publishers/{expected_id}.json. Verifying a publisher who has no record "
                        "is a tier attached to nothing")
            continue

        if expected_id in policy.OFFICIAL_PUBLISHERS:
            report.fail("VERIFICATION_REDUNDANT", where,
                        f"{expected_id!r} is one of ours and is already official, which is decided in "
                        "tools/registry/policy.py. A verification record beside it would be a second, weaker "
                        "answer to a question that already has one")
            continue

        # Added or edited, either of which is a maintainer deciding something. A record that has sat
        # in the tree since before this pull request is not.
        #
        # **Whether this is a change is a property of the difference, so with no base ref there is no
        # question to answer** — the same reason `_check_keys_pinned` is skipped there rather than
        # guessed at. Without one, every record looks new, and refusing the whole tree for want of a
        # label a local run cannot have is a check that has stopped being about anything. CI always
        # passes a base ref, and the report says so in a note.
        previous = gitref.read_json_at(repo, base_ref, where) if base_ref is not None else None
        changed = base_ref is not None and previous != document

        if changed and not allow_verification:
            report.fail("VERIFICATION_UNAPPROVED", where,
                        "this pull request writes a verification. Only a maintainer decides that somebody is "
                        "who they say they are, so it needs the 'verification' label — a submitter opening "
                        "this diff is exactly the self-claim the tier exists to be immune to")

        # Unchanged records are not re-fetched on a pull request, for the same reason an untouched
        # archive is not: a submission should cost what it proposes and not what everybody else
        # published. The audit runs with --recheck-all and re-reads every one of them.
        #
        # With no base ref, read them all: "did this change" is unanswerable there, and re-reading a
        # document is the half of this check that needs no history at all.
        if document["status"] == "active" and not offline and (changed or recheck_all or base_ref is None):
            failure = verification.check_evidence(expected_id, document, origins)
            if failure is not None:
                report.fail(failure[0], where, failure[1])
                continue

        found[expected_id] = document

    _check_verifications_append_only(report, repo, base_ref, files)

    return found


def _check_verifications_append_only(report: Report, repo: str, base_ref: str | None,
                                     files: list[str]) -> None:
    """A verification is withdrawn, never deleted — the rule a revoked key and a withdrawn version
    already follow, and it matters here for the same reason. *"We checked this and then stopped
    believing it"* is a fact worth being able to read afterwards; a file that quietly disappears
    leaves a publisher who was verified last week looking as though they never were."""

    if base_ref is None:
        return

    present = set(files)
    for path in gitref.paths_at(repo, base_ref, "verification"):
        name = os.path.basename(path)
        if name.endswith(".json") and name not in present:
            report.fail("VERIFICATION_REMOVED", f"verification/{name}",
                        "this verification was deleted. Set status to 'withdrawn' with a reason instead — the "
                        "history of what we once checked is what a later reader has to be able to see")


# ---------------------------------------------------------------------------------------------
# featuring


def check_featured(report: Report, repo: str, validator, plugin_dirs: list[str],
                   base_ref: str | None, allow_curation: bool) -> None:
    """The shop window: who may fill it, and the two things that make an entry meaningless.

    **This is the only check in this file with nothing to fetch, because there is nothing to check.**
    Every other rule here asks whether a claim survives contact with the world — do the bytes hash to
    that, does the evidence still say this. Featuring makes no such claim: it says somebody decided
    something. So what a validator can do about it is narrow, and pretending otherwise would be the
    same overclaim the tier documentation spends a page refusing.

    What it can do:

    **Refuse a diff nobody with write access asked for.** The `curation` label, exactly as
    `verification` works and for a related reason. There the self-claim being blocked is *"I am who I
    say I am"*; here it is *"put me in the window"*, which is a smaller lie and a much more tempting
    one — it is the field a submitter would most like to write, which is precisely why there is no
    field and why the file is not one a submission can reach.

    **Refuse an entry that points at nothing.** A featured id with no plugin directory, or one whose
    every version has been withdrawn, is a window with an empty box in it. Somebody clicks it and is
    offered nothing, and the fault looks like the store's rather than the list's.

    **Refuse a window with everything in it**, which distinguishes nothing and is a second copy of
    the catalogue in an order nobody chose.

    **Refuse the same plugin twice**, including once as spotlight and once in the list. Two rows for
    one plugin is a list somebody edited without reading, and resolving it quietly would hide that.

    What it cannot do, and does not pretend to: say whether this is a good plugin to feature. That is
    the judgement, and it is the whole of what the label is asserting somebody made.
    """

    document = curation.load(repo)
    path = curation.PATH.replace(os.sep, "/")
    exists = os.path.isfile(os.path.join(repo, curation.PATH))

    if exists and document is None:
        report.fail("SCHEMA_INVALID", path,
                    "this file is not readable JSON. It is skipped by the index generator rather than "
                    "taking the whole feed down for a shop window, so a malformed one publishes nothing "
                    "and says nothing — which is why it is refused here instead")
        return

    if document is None:
        # No file is "nothing is featured", which is the ordinary state and is this registry's today.
        return

    if not check_schema(report, validator, document, path):
        return

    # Added or edited is a maintainer deciding something; a file that has sat in the tree since before
    # this pull request is not. Whether that is a change is a property of the difference, so with no
    # base ref there is no question to answer — the same reasoning `check_verifications` gives.
    previous = gitref.read_json_at(repo, base_ref, path) if base_ref is not None else None
    if base_ref is not None and previous != document and not allow_curation:
        report.fail("CURATION_UNAPPROVED", path,
                    "this pull request edits the featured list. Which plugins go in the window is an "
                    "editorial decision and only a maintainer takes it, so it needs the 'curation' label. "
                    "Note what this is not: featuring says we put something in front of you and never that "
                    "anybody checked it, which is what the tiers are for and what they are refused without")

    known = set(plugin_dirs)
    rows = curation.entries(document)
    one = curation.spotlight(document)

    if len(rows) > policy.MAX_FEATURED:
        report.fail("CURATION_TOO_MANY", path,
                    f"{len(rows)} plugins are featured and the window holds {policy.MAX_FEATURED}. Past "
                    "some length featuring stops distinguishing anything and becomes a second copy of the "
                    "catalogue in an arbitrary order")

    seen: set[str] = set()
    if one is not None:
        seen.add(one["plugin"])

    for row in rows:
        plugin_id = row["plugin"]
        if plugin_id in seen:
            report.fail("CURATION_DUPLICATE", path,
                        f"{plugin_id!r} is featured more than once, or is both the spotlight and on the "
                        "list. One plugin, one place in the window — two rows for one plugin is a list "
                        "somebody edited without reading, and resolving it quietly would hide that")
        seen.add(plugin_id)

    for plugin_id in ([one["plugin"]] if one is not None else []) + [r["plugin"] for r in rows]:
        if plugin_id not in known:
            report.fail("CURATION_UNKNOWN_PLUGIN", path,
                        f"{plugin_id!r} is featured and there is no plugins/{plugin_id}/. A window pointing "
                        "at nothing is worse than an empty one: somebody follows it and the store looks "
                        "broken rather than the list")
            continue

        manifest, problem = load_json(os.path.join(repo, "plugins", plugin_id, "plugin.json"))
        if problem is not None or not isinstance(manifest, dict):
            continue    # check_plugins owns this failure and will report it in its own words
        if not curation.installable(manifest):
            report.fail("CURATION_NOTHING_OFFERED", path,
                        f"every version of {plugin_id!r} has been withdrawn, so featuring it puts an empty "
                        "box in the window. Take it off the list — a withdrawn plugin stays in the "
                        "catalogue and stays searchable, which is the right amount of visible")


# ---------------------------------------------------------------------------------------------
# plugins


SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def check_plugins(report: Report, repo: str, dirs: list[str], validator,
                  publishers: dict[str, dict], base_ref: str | None,
                  origins: fetch.OriginMap, offline: bool, recheck_all: bool) -> dict[str, dict]:
    plugins: dict[str, dict] = {}
    seen_lower: dict[str, str] = {}

    for directory in dirs:
        where = f"plugins/{directory}/plugin.json"
        document, problem = load_json(os.path.join(repo, "plugins", directory, "plugin.json"))
        if problem is not None:
            report.fail("SCHEMA_INVALID", where, problem)
            continue
        if not check_schema(report, validator, document, where):
            continue

        plugin_id = document["id"]

        # Duplicate ids are checked before the directory rule, and against the id the *manifest*
        # claims rather than the directory it sits in. The filesystem already stops two directories
        # sharing a name; what it does not stop is a second manifest quietly claiming an id that is
        # already somebody's, which is the shape an id being reassigned actually takes.
        lower = plugin_id.lower()
        if lower in seen_lower:
            report.fail("ID_DUPLICATE", where,
                        f"id {plugin_id!r} is already claimed by {seen_lower[lower]}. Ids are allocated "
                        "once and never reassigned — an entitlement, a pinned key and an installed copy on "
                        "somebody's hub all point at this string")
            continue
        seen_lower[lower] = where

        if plugin_id != directory:
            report.fail("LAYOUT_DIR_ID_MISMATCH", where,
                        f"the manifest says id {plugin_id!r} but it lives in plugins/{directory}/. "
                        "The directory is the id, so that one id can never have two manifests")
            continue

        if document["license"] not in policy.ALLOWED_LICENSES:
            report.fail("LICENSE_NOT_ALLOWED", where,
                        f"{document['license']!r} is not one of the licences the registry carries. "
                        f"Allowed today: {', '.join(policy.ALLOWED_LICENSES)}")

        publisher = publishers.get(document["publisher"])
        if publisher is None:
            report.fail("PUBLISHER_UNKNOWN", where,
                        f"there is no publishers/{document['publisher']}.json. A publisher is a record in "
                        "this repository, not a string in a manifest")
            continue

        previous = gitref.read_json_at(repo, base_ref, where) if base_ref is not None else None
        if previous is not None:
            _check_plugin_append_only(report, where, previous, document)

        _check_versions(report, where, document, previous, publisher, origins, offline, recheck_all)

        if not offline:
            problem = fetch.resolves(document["source"], origins)
            if problem is not None:
                report.fail("SOURCE_UNRESOLVED", where,
                            f"{problem}. The source link is shown beside the plugin permanently; a dead one "
                            "is worse than none, because it reads as provenance")

        plugins[plugin_id] = document

    return plugins


def _check_plugin_append_only(report: Report, where: str, previous: dict, current: dict) -> None:
    if previous.get("publisher") != current.get("publisher"):
        report.fail("PUBLISHER_REASSIGNED", where,
                    f"the publisher changed from {previous.get('publisher')!r} to {current.get('publisher')!r}. "
                    "A plugin id belongs to whoever first published it, permanently — an id that changes hands "
                    "is a hub trusting different software under a name it already agreed to")

    before = {v["version"]: v for v in previous.get("versions", []) if isinstance(v, dict) and "version" in v}
    after = {v["version"]: v for v in current.get("versions", [])}

    for version, old in before.items():
        if version not in after:
            report.fail("VERSION_REMOVED", where,
                        f"version {version} was deleted. A published version is withdrawn, never removed: a hub "
                        "that has it installed keeps running it, and needs to be told why it should not")
            continue
        new = after[version]
        old_body = {k: v for k, v in old.items() if k != "withdrawn"}
        new_body = {k: v for k, v in new.items() if k != "withdrawn"}
        if old_body != new_body:
            report.fail("VERSION_MUTATED", where,
                        f"version {version} was edited after publication. Publish a new version instead — the "
                        "digests in this file are what a hub already checked its copy against")
        if "withdrawn" in old and "withdrawn" not in new:
            report.fail("VERSION_MUTATED", where,
                        f"version {version} was un-withdrawn. Publish a new version instead")


def _check_versions(report: Report, where: str, document: dict, previous: dict | None, publisher: dict,
                    origins: fetch.OriginMap, offline: bool, recheck_all: bool) -> None:
    keys = {key["id"]: key for key in publisher["keys"]}
    seen: set[str] = set()

    # A version that is byte-identical to what was already published has already had its bytes
    # fetched, hashed and signature-checked, on the pull request that merged it — and anything that
    # has moved since is caught as VERSION_MUTATED regardless. So a pull request downloads what it
    # is actually proposing, rather than the publisher's whole back catalogue every time somebody
    # bumps a patch version.
    #
    # What that gives up is noticing link rot in something published months ago. That is real, and
    # it is the audit workflow's job: it runs on a schedule with --recheck-all and fetches
    # everything.
    already = {}
    if previous is not None and not recheck_all:
        already = {v["version"]: v for v in previous.get("versions", []) if isinstance(v, dict) and "version" in v}

    for version in document["versions"]:
        label = version["version"]
        vwhere = f"{where} [{label}]"
        unchanged = label in already and already[label] == version

        if label in seen:
            report.fail("VERSION_DUPLICATE", vwhere, f"version {label} is declared twice")
            continue
        seen.add(label)

        if version["abi"] not in policy.SUPPORTED_ABIS:
            report.fail("ABI_UNSUPPORTED", vwhere,
                        f"abi {version['abi']} is not one this registry carries "
                        f"({', '.join(str(a) for a in policy.SUPPORTED_ABIS)}). A hub refuses a plugin from "
                        "outside its own range with a sentence, and it should never have to")

        declared = set(version["archives"])
        unsupported = set(version.get("unsupportedRids", {}))
        overlap = declared & unsupported
        if overlap:
            report.fail("RID_COVERAGE", vwhere,
                        f"{', '.join(sorted(overlap))} is both published and declared unsupported")
        missing = set(policy.RIDS) - declared - unsupported
        if missing:
            report.fail("RID_COVERAGE", vwhere,
                        f"no build for {', '.join(sorted(missing))}, and no reason given. Publishing one "
                        "architecture is allowed; leaving the other unexplained is not, because the hub has to "
                        "tell someone whether this plugin has no build for their box or simply failed")

        for rid, archive in sorted(version["archives"].items()):
            _check_archive(report, f"{vwhere} {rid}", document, version, rid, archive, keys, origins,
                           offline or unchanged)


def _check_archive(report: Report, where: str, document: dict, version: dict, rid: str,
                   archive: dict, keys: dict[str, dict], origins: fetch.OriginMap, offline: bool) -> None:
    key = keys.get(archive["keyId"])
    if key is None:
        report.fail("KEY_UNKNOWN", where,
                    f"signed with key {archive['keyId']!r}, which is not pinned to publisher "
                    f"{document['publisher']!r}. Every version after the first must be signed by a key this "
                    "publisher already had")
        return
    if key["status"] != "active":
        report.fail("KEY_REVOKED", where,
                    f"key {archive['keyId']!r} is revoked and cannot sign anything new")
        return
    if key["algorithm"] != policy.SIGNATURE_ALGORITHM:
        report.fail("KEY_UNKNOWN", where, f"key {archive['keyId']!r} is not {policy.SIGNATURE_ALGORITHM}")
        return

    if archive["size"] > policy.MAX_ARCHIVE_BYTES:
        # Refused on the declared size, before anything is fetched — which is the same order the hub
        # is asked to work in, and for the same reason: "afterwards" means a runner that has already
        # written however many gigabytes somebody else chose.
        report.fail("SIZE_BUDGET", where,
                    f"{archive['size']} bytes is past the {policy.MAX_ARCHIVE_BYTES}-byte ceiling. The "
                    "appliance's data partition is 3 GiB and does not grow")
        return

    if offline:
        return

    with tempfile.TemporaryDirectory() as scratch:
        try:
            got = fetch.download(archive["url"], origins, scratch)
        except fetch.FetchError as error:
            report.fail("URL_UNRESOLVED", where, str(error))
            return

        if got.sha256 != archive["sha256"]:
            report.fail("SHA256_MISMATCH", where,
                        f"the archive hashes to {got.sha256}, the manifest says {archive['sha256']}. "
                        "The digest is the whole integrity story for a tarball; a hub will refuse these bytes")
            return

        if got.size != archive["size"]:
            report.fail("SIZE_MISMATCH", where,
                        f"the archive is {got.size} bytes, the manifest says {archive['size']}")

        problem = fetch.verify_signature(got.path, archive["signature"], key["publicKey"])
        if problem is not None:
            report.fail("SIGNATURE_INVALID", where,
                        f"{problem}. This is the check that says an update came from whoever published the "
                        "first version, and it is the only guarantee the registry actually makes")
            return

        _check_archive_contents(report, where, document, version, rid, got.path)


def _check_archive_contents(report: Report, where: str, document: dict, version: dict,
                            rid: str, path: str) -> None:
    """Read the plugin.json inside the archive and make it agree with the submission.

    One logical plugin, several builds. If the archives disagree about id, version or abi then
    they are different software wearing one name, and the hub would have no way to notice.
    """

    try:
        with tarfile.open(path, "r:gz") as archive:
            member = None
            for candidate in archive.getmembers():
                normalised = candidate.name.lstrip("./")
                if normalised == "plugin.json" and candidate.isfile():
                    member = candidate
                    break
            if member is None:
                report.fail("ARCHIVE_MALFORMED", where,
                            "there is no plugin.json at the root of the archive. It is what tells the hub what "
                            "to run, and without it the only way to learn what a plugin is would be to run it")
                return
            if member.size > 256 * 1024:
                report.fail("ARCHIVE_MALFORMED", where, "the archive's plugin.json is implausibly large")
                return
            handle = archive.extractfile(member)
            raw = handle.read() if handle is not None else b""
    except tarfile.TarError as error:
        report.fail("ARCHIVE_MALFORMED", where, f"the archive is not a readable gzipped tar: {error}")
        return
    except OSError as error:  # pragma: no cover
        report.fail("ARCHIVE_MALFORMED", where, f"the archive could not be read: {error}")
        return

    try:
        embedded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        report.fail("ARCHIVE_MALFORMED", where, f"the archive's plugin.json is not readable JSON: {error}")
        return

    for field, expected in (("id", document["id"]), ("version", version["version"]), ("abi", version["abi"])):
        if embedded.get(field) != expected:
            report.fail("ARCHIVE_MANIFEST_MISMATCH", where,
                        f"the archive's plugin.json says {field}={embedded.get(field)!r}, the submission says "
                        f"{expected!r}. The file the hub reads and the file a reviewer reads have to be the "
                        "same claim")

    if "rid" in embedded and embedded["rid"] != rid:
        report.fail("ARCHIVE_MANIFEST_MISMATCH", where,
                    f"the archive's plugin.json says rid={embedded['rid']!r}, but it is published as {rid}")

    exec_argv = embedded.get("exec")
    if not isinstance(exec_argv, list) or not exec_argv or not all(isinstance(a, str) and a for a in exec_argv):
        report.fail("ARCHIVE_MALFORMED", where,
                    "the archive's plugin.json has no usable 'exec' argv, so nothing in it can be launched")


# ---------------------------------------------------------------------------------------------
# entry point


def validate(repo: str, base_ref: str | None, origins: fetch.OriginMap,
             offline: bool, allow_rotation: bool, recheck_all: bool = False,
             allow_verification: bool = False, allow_curation: bool = False) -> Report:
    report = Report()

    for marker in REPO_ROOT_MARKERS:
        if not os.path.isdir(os.path.join(repo, marker)):
            print(f"{repo} does not look like the registry: no {marker}/ in it", file=sys.stderr)
            raise SystemExit(2)

    if base_ref is not None and not gitref.ref_exists(repo, base_ref):
        print(f"base ref {base_ref!r} is not a commit in {repo}", file=sys.stderr)
        raise SystemExit(2)

    if base_ref is None:
        report.note("no base ref given, so nothing was checked about pinning, reassignment, edits to "
                    "published versions, or whether a verification or a featured list in this tree is "
                    "one a maintainer approved. CI always passes one.")
    if offline:
        report.note("offline, so no URL was fetched, no digest was checked and no signature was verified. "
                    "CI never runs this way.")
    if origins:
        report.note("an origin map is in force, so URLs were rewritten before fetching. This is for the "
                    "test suite; CI passes none.")

    submission = schema_validator(repo, "submission.schema.json")
    publisher_schema = schema_validator(repo, "publisher.schema.json")
    verification_schema = schema_validator(repo, "verification.schema.json")
    featured_schema = schema_validator(repo, "featured.schema.json")

    publisher_files, plugin_dirs, verification_files = check_layout(report, repo)
    publishers = check_publishers(report, repo, publisher_files, publisher_schema, base_ref, allow_rotation)
    check_verifications(report, repo, verification_files, verification_schema, publishers, base_ref,
                        origins, offline, allow_verification, recheck_all)
    check_plugins(report, repo, plugin_dirs, submission, publishers, base_ref, origins, offline, recheck_all)
    check_featured(report, repo, featured_schema, plugin_dirs, base_ref, allow_curation)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the reMaestro extensions registry.")
    parser.add_argument("--repo", default=".", help="the registry checkout to validate")
    parser.add_argument("--base-ref", default=None,
                        help="what the registry looked like before this change, e.g. origin/main. "
                             "Without it, pinning and append-only rules cannot be checked at all.")
    parser.add_argument("--offline", action="store_true",
                        help="skip everything that leaves the machine. For a quick local check; never CI.")
    parser.add_argument("--recheck-all", action="store_true",
                        help="fetch and verify every published version, not only the ones this change "
                             "touches. For the scheduled audit, which is what catches link rot.")
    parser.add_argument("--allow-key-rotation", action="store_true",
                        help="permit a publisher to add a key. Set by CI only when the PR carries the "
                             "'key-rotation' label.")
    parser.add_argument("--allow-verification", action="store_true",
                        help="permit this change to write a publisher verification. Set by CI only when the "
                             "PR carries the 'verification' label, which only a maintainer can apply.")
    parser.add_argument("--allow-curation", action="store_true",
                        help="permit this change to edit the featured list. Set by CI only when the PR "
                             "carries the 'curation' label, which only a maintainer can apply.")
    parser.add_argument("--origin-map", default=os.environ.get("REGISTRY_ORIGIN_MAP"),
                        help="rewrite URL prefixes before fetching, 'from=to' comma separated. Test suite only.")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)

    try:
        origins = fetch.OriginMap.from_env(args.origin_map)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    allow_rotation = args.allow_key_rotation or os.environ.get("REGISTRY_ALLOW_KEY_ROTATION") == "1"
    allow_verification = args.allow_verification or os.environ.get("REGISTRY_ALLOW_VERIFICATION") == "1"
    allow_curation = args.allow_curation or os.environ.get("REGISTRY_ALLOW_CURATION") == "1"
    report = validate(os.path.abspath(args.repo), args.base_ref, origins, args.offline,
                      allow_rotation, args.recheck_all, allow_verification, allow_curation)

    if args.json:
        print(json.dumps({
            "ok": report.ok,
            "notes": report.notes,
            "findings": [{"code": f.code, "where": f.where, "message": f.message} for f in report.findings],
        }, indent=2))
    else:
        for note in report.notes:
            print(f"note: {note}")
        for finding in report.findings:
            print(str(finding))
        print()
        print("the registry validates" if report.ok
              else f"{len(report.findings)} problem(s); nothing is merged until they are gone")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
