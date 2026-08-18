"""Sabotage every rule, one at a time, and watch it refuse.

A validator nobody has watched reject something is not a validator. So each scenario below takes
the clean registry, breaks exactly one thing, and asserts on the *code* the validator emits — not
on the exit status alone, which would be satisfied by any failure for any reason, including the
validator crashing.

Two controls run either side of the sabotage: the clean tree passes at the start and again at the
end. If a control ever fails, every "correctly rejected" in between means nothing, because a
harness that rejects everything looks identical to one that works.

    python3 tests/test_registry.py

Needs `openssl` and `git` on PATH and `jsonschema` importable. Touches no network: the artifacts
are served from loopback by this process.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import fixture  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The one sentence a tier is never allowed to be published without. Asserted against three documents
# below; if you reword it, reword it in all four places or the suite says which one you missed.
TIER_DISCLAIMER = "Verified means we checked who a publisher is. It never means a plugin is safe."

# The same job, one authority further out. A tier is refused unless something can be shown; featuring
# is refused unless a maintainer asked for it, and there is nothing to show either way. Rendering the
# two as two kinds of badge is the single mistake this whole area is shaped to make unavailable, so
# the sentence that says so is asserted against the documents rather than trusted to stay written.
FEATURED_DISCLAIMER = "Featured says we put it in the window. It never says anybody checked it."


class Outcome:
    def __init__(self, returncode: int, payload: dict, stderr: str) -> None:
        self.returncode = returncode
        self.payload = payload
        self.stderr = stderr

    @property
    def codes(self) -> list[str]:
        return [f["code"] for f in self.payload.get("findings", [])]

    def message_for(self, code: str) -> str:
        for finding in self.payload.get("findings", []):
            if finding["code"] == code:
                return finding["message"]
        return ""


def run_validator(repo: str, origin_map: str, *, base_ref: str | None = "HEAD",
                  allow_rotation: bool = False, recheck_all: bool = False,
                  allow_verification: bool = False, allow_curation: bool = False) -> Outcome:
    args = [sys.executable, "-m", "registry.validate", "--repo", repo, "--json",
            "--origin-map", origin_map]
    if base_ref:
        args += ["--base-ref", base_ref]
    if allow_rotation:
        args.append("--allow-key-rotation")
    if recheck_all:
        args.append("--recheck-all")
    if allow_verification:
        args.append("--allow-verification")
    if allow_curation:
        args.append("--allow-curation")

    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tools"))
    result = subprocess.run(args, capture_output=True, text=True, env=env, cwd=ROOT)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"findings": [], "ok": False, "raw": result.stdout}
    return Outcome(result.returncode, payload, result.stderr)


# ---------------------------------------------------------------------------------------------
# the sabotage scenarios. each takes (repo, ctx) and breaks exactly one thing.


def _plugin(repo):
    return fixture.read_json(fixture.plugin_path(repo))


def _write_plugin(repo, document):
    fixture.write_json(fixture.plugin_path(repo), document)


def _publisher(repo):
    return fixture.read_json(fixture.publisher_path(repo))


def _write_publisher(repo, document):
    fixture.write_json(fixture.publisher_path(repo), document)


def _new_version(document):
    return document["versions"][-1]


def unknown_field(repo, ctx):
    document = _plugin(repo)
    document["price"] = "9.99"
    _write_plugin(repo, document)


def missing_required_field(repo, ctx):
    document = _plugin(repo)
    del document["license"]
    _write_plugin(repo, document)


def not_semver(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["version"] = "v1.1"
    _write_plugin(repo, document)


def id_does_not_match_directory(repo, ctx):
    document = _plugin(repo)
    document["id"] = "com.example.other"
    _write_plugin(repo, document)


def duplicate_id(repo, ctx):
    second = os.path.join(repo, "plugins", "com.example.lamp2")
    os.makedirs(second)
    document = _plugin(repo)  # still claims com.example.lamp
    fixture.write_json(os.path.join(second, "plugin.json"), document)


def duplicate_version(repo, ctx):
    document = _plugin(repo)
    document["versions"].append(copy.deepcopy(_new_version(document)))
    _write_plugin(repo, document)


def unknown_publisher(repo, ctx):
    document = _plugin(repo)
    document["publisher"] = "com.somebody.else"
    _write_plugin(repo, document)


def publisher_reassigned(repo, ctx):
    fixture.write_json(os.path.join(repo, "publishers", "com.newowner.json"), {
        "id": "com.newowner",
        "name": "New Owner",
        "contact": "https://github.com/newowner",
        "keys": [{
            "id": "2026-02",
            "algorithm": "ecdsa-p256-sha256",
            "publicKey": ctx["impostor_key"].public_key,
            "addedAt": "2026-02-01",
            "status": "active",
        }],
    })
    document = _plugin(repo)
    document["publisher"] = "com.newowner"
    for version in document["versions"]:
        for archive in version["archives"].values():
            archive["keyId"] = "2026-02"
    _write_plugin(repo, document)


def key_not_pinned(repo, ctx):
    document = _plugin(repo)
    for archive in _new_version(document)["archives"].values():
        archive["keyId"] = "some-other-key"
    _write_plugin(repo, document)


def signed_by_another_key(repo, ctx):
    """The realistic attack: the same plugin id, a new version, signed by somebody else."""
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"] = dict(ctx["extras"]["lamp-1.1.0-impostor.tar.gz"])
    _write_plugin(repo, document)


def pinned_key_swapped(repo, ctx):
    publisher = _publisher(repo)
    publisher["keys"][0]["publicKey"] = ctx["impostor_key"].public_key
    _write_publisher(repo, publisher)


def pinned_key_deleted(repo, ctx):
    publisher = _publisher(repo)
    publisher["keys"] = [{
        "id": "2026-09",
        "algorithm": "ecdsa-p256-sha256",
        "publicKey": ctx["impostor_key"].public_key,
        "addedAt": "2026-09-01",
        "status": "active",
    }]
    _write_publisher(repo, publisher)


def key_added_without_approval(repo, ctx):
    publisher = _publisher(repo)
    publisher["keys"].append({
        "id": "2026-09",
        "algorithm": "ecdsa-p256-sha256",
        "publicKey": ctx["impostor_key"].public_key,
        "addedAt": "2026-09-01",
        "status": "active",
    })
    _write_publisher(repo, publisher)


def revoked_key_signs(repo, ctx):
    publisher = _publisher(repo)
    publisher["keys"][0]["status"] = "revoked"
    _write_publisher(repo, publisher)


def published_version_edited(repo, ctx):
    """Repoint an already-published version at different bytes.

    Chosen because the replacement passes every other check: it is a real tarball, correctly
    signed by the pinned key, with the right plugin.json inside. Only the base ref knows the
    version used to point somewhere else.
    """
    document = _plugin(repo)
    document["versions"][0]["archives"]["linux-x64"] = \
        dict(ctx["extras"]["lamp-1.0.0-linux-x64-rebuilt.tar.gz"])
    _write_plugin(repo, document)


def published_version_removed(repo, ctx):
    document = _plugin(repo)
    document["versions"] = [v for v in document["versions"] if v["version"] != "1.0.0"]
    _write_plugin(repo, document)


def url_does_not_resolve(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"]["url"] = \
        f"{fixture.ARTIFACT_ORIGIN}/lamp-1.1.0-that-was-never-uploaded.tar.gz"
    _write_plugin(repo, document)


def digest_does_not_match(repo, ctx):
    document = _plugin(repo)
    archive = _new_version(document)["archives"]["linux-arm64"]
    original = archive["sha256"]
    archive["sha256"] = ("0" if original[0] != "0" else "1") + original[1:]
    _write_plugin(repo, document)


def size_does_not_match(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"]["size"] += 1
    _write_plugin(repo, document)


def over_size_budget(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"]["size"] = 900 * 1024 * 1024
    _write_plugin(repo, document)


def abi_from_the_future(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["abi"] = 7
    _write_plugin(repo, document)


def architecture_silently_missing(repo, ctx):
    document = _plugin(repo)
    del _new_version(document)["archives"]["linux-x64"]
    _write_plugin(repo, document)


def architecture_declared_unsupported(repo, ctx):
    """The control for the one above: saying so out loud is allowed, and must pass."""
    document = _plugin(repo)
    version = _new_version(document)
    del version["archives"]["linux-x64"]
    version["unsupportedRids"] = {"linux-x64": "no x64 build until the CI runner exists"}
    _write_plugin(repo, document)


def licence_not_carried(repo, ctx):
    document = _plugin(repo)
    document["license"] = "LicenseRef-Acme-Commercial"
    _write_plugin(repo, document)


def archive_disagrees_with_submission(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"] = \
        dict(ctx["extras"]["lamp-1.1.0-wrong-version-inside.tar.gz"])
    _write_plugin(repo, document)


def archive_has_no_manifest(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"] = dict(ctx["extras"]["lamp-1.1.0-no-manifest.tar.gz"])
    _write_plugin(repo, document)


def archive_has_nothing_to_launch(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"] = dict(ctx["extras"]["lamp-1.1.0-no-exec.tar.gz"])
    _write_plugin(repo, document)


def archive_is_not_a_tarball(repo, ctx):
    document = _plugin(repo)
    _new_version(document)["archives"]["linux-arm64"] = dict(ctx["extras"]["lamp-1.1.0-not-a-tarball.tar.gz"])
    _write_plugin(repo, document)


def source_does_not_resolve(repo, ctx):
    document = _plugin(repo)
    document["source"] = f"{fixture.ARTIFACT_ORIGIN}/source/there-is-nothing-here"
    _write_plugin(repo, document)


def artifact_committed_to_the_registry(repo, ctx):
    with open(os.path.join(repo, "plugins", fixture.PLUGIN_ID, "lamp-1.1.0.tar.gz"), "wb") as handle:
        handle.write(b"the bytes do not live here")


# ---------------------------------------------------------------------------------------------
# tiers. `official` is published by us, `verified` means somebody checked who a publisher is, and
# `unverified` is everybody else — and **none of the three says a plugin is safe.**
#
# The rule the sabotage below is really about: a tier a publisher can write is a tier a publisher
# has asserted. So the first two scenarios are the self-claim, refused by the schema rather than by
# a rule somebody has to remember, and the rest are a maintainer's record being wrong in each of the
# ways it can be wrong.


def tier_claimed_in_a_plugin_manifest(repo, ctx):
    """The self-claim, in the document a submitter actually writes."""
    document = _plugin(repo)
    document["tier"] = "verified"
    _write_plugin(repo, document)


def tier_claimed_in_a_publisher_record(repo, ctx):
    """And in the other one they write. `publishers/<id>.json` is submitted by its own subject, which
    is the whole reason the tier is not a field in it."""
    publisher = _publisher(repo)
    publisher["tier"] = "verified"
    _write_publisher(repo, publisher)


def verification_written_without_approval(repo, ctx):
    """A pull request that verifies somebody. Only a maintainer decides this, and the label is how
    they say so — the same mechanism a key rotation goes through, for the same reason."""
    fixture.write_json(fixture.verification_path(repo, "invalid.newcomer"), {
        **fixture.verification_record("invalid.newcomer"),
        "evidence": "https://newcomer.invalid/.well-known/remaestro-publisher.txt",
    })
    fixture.write_json(os.path.join(repo, "publishers", "invalid.newcomer.json"), {
        "id": "invalid.newcomer",
        "name": "Newcomer",
        "contact": "https://github.com/newcomer",
        "keys": [{
            "id": "2026-03",
            "algorithm": "ecdsa-p256-sha256",
            "publicKey": ctx["impostor_key"].public_key,
            "addedAt": "2026-03-01",
            "status": "active",
        }],
    })


def evidence_at_a_url_the_submitter_chose(repo, ctx):
    """**The attack the derivation exists to stop.**

    The document at that URL is real, is served, and says exactly the right thing — it is the same
    file, byte for byte. The only thing wrong with it is that it is somewhere the record points at
    rather than somewhere the publisher id implies, which is the difference between checking who
    somebody is and checking whatever they chose to serve.
    """
    record = fixture.read_json(fixture.verification_path(repo))
    record["evidence"] = f"{fixture.ARTIFACT_ORIGIN}/chosen-evidence.txt"
    fixture.write_json(fixture.verification_path(repo), record)


def verification_for_a_publisher_with_no_record(repo, ctx):
    fixture.write_json(fixture.verification_path(repo, "invalid.nobody"),
                       fixture.verification_record("invalid.nobody"))


def verification_named_for_another_publisher(repo, ctx):
    """The file says one publisher and is named for another. Whichever the reader trusts, one of
    them is getting a tier nobody checked."""
    record = fixture.verification_record()
    record["publisher"] = "invalid.somebody-else"
    fixture.write_json(fixture.verification_path(repo), record)


def official_claimed_by_a_verification(repo, ctx):
    """Official is published by us and comes from a tuple in our own source. A record that could
    spell it would be a domain buying it."""
    record = fixture.verification_record()
    record["tier"] = "official"
    fixture.write_json(fixture.verification_path(repo), record)


def a_tier_that_does_not_exist(repo, ctx):
    record = fixture.verification_record()
    record["tier"] = "gold"
    fixture.write_json(fixture.verification_path(repo), record)


def verification_quietly_deleted(repo, ctx):
    """Withdrawn, never deleted — the rule a revoked key and a withdrawn version already follow."""
    os.remove(fixture.verification_path(repo))


def official_publisher_given_a_verification_record(repo, ctx):
    """One of ours, handed a second and weaker answer to a question that already has one. Official
    is decided in our own source; a record beside it is either redundant or a downgrade waiting to
    happen, and neither is worth being able to write."""
    official = "app.remaestro"
    fixture.write_json(os.path.join(repo, "publishers", f"{official}.json"), {
        "id": official,
        "name": "reMaestro",
        "contact": "https://github.com/Redth",
        "keys": [{
            "id": "2026-01",
            "algorithm": "ecdsa-p256-sha256",
            "publicKey": ctx["impostor_key"].public_key,
            "addedAt": "2026-01-01",
            "status": "active",
        }],
    })
    fixture.write_json(fixture.verification_path(repo, official), fixture.verification_record(official))


def something_else_in_the_verification_directory(repo, ctx):
    with open(os.path.join(repo, "verification", "notes.txt"), "w", encoding="utf-8") as handle:
        handle.write("this directory holds records and nothing else")


# ---- and the tier changes that are allowed --------------------------------------------------


def verification_withdrawn(repo, ctx):
    """A verification that stopped being true, said out loud. Allowed, with the label, and the
    publisher drops back to unverified rather than the record vanishing."""
    record = fixture.read_json(fixture.verification_path(repo))
    record["status"] = "withdrawn"
    record["withdrawn"] = {"at": "2026-09-01", "reason": "the domain lapsed and was re-registered"}
    fixture.write_json(fixture.verification_path(repo), record)


def verification_rechecked(repo, ctx):
    """A maintainer looking at an existing verification again. With the label this passes — and it
    passes by *fetching the evidence*, which is the one path in this whole area where the happy case
    has to be watched working: a check that only ever refuses is a check nobody can tell from a
    blanket denial."""
    record = fixture.read_json(fixture.verification_path(repo))
    record["note"] = "re-read the well-known document by hand"
    fixture.write_json(fixture.verification_path(repo), record)


# ---- featuring: the shop window, and the four ways to point it at nothing --------------------
#
# Read these against the tier sabotages above, because the pair is the point. A tier is refused
# unless the evidence still resolves at a URL nobody chose; featuring has no evidence, and every
# check below is about the *window* rather than about the plugin — is somebody with write access
# asking, does it point at something, and does it distinguish anything. Nothing here can decide
# whether a plugin deserves to be featured, and nothing here pretends to.


def _featured(repo):
    return fixture.read_json(fixture.featured_path(repo))


def _write_featured(repo, document):
    fixture.write_json(fixture.featured_path(repo), document)


def a_plugin_featuring_itself(repo, ctx):
    """**The self-claim, in the document a submitter actually writes.**

    This is the one that matters, and it is the direct analogue of `tier_claimed_in_a_plugin_manifest`
    one line of authority further out. A publisher opening a pull request has exactly two documents
    they may write, and neither has a field that reaches the window: `additionalProperties: false`
    makes it a schema failure rather than a field somebody has to remember to ignore.
    """
    document = _plugin(repo)
    document["featured"] = True
    _write_plugin(repo, document)


def a_plugin_spotlighting_itself(repo, ctx):
    """The same claim spelled the other way, because a guard that only knows one spelling is a guard
    against a typo. `spotlight` is a different word, the same self-assertion, and the same refusal —
    and it is refused by the schema being closed rather than by a list of forbidden names, which is
    what makes the third spelling refused too."""
    document = _plugin(repo)
    document["spotlight"] = {"blurb": "the best lamp plugin there is, honestly"}
    _write_plugin(repo, document)


def a_featured_list_beside_a_manifest(repo, ctx):
    """Not a field this time but a file, dropped in the plugin's own directory where a publisher can
    write. A directory that accepted it would have made the schema's refusal decorative."""
    fixture.write_json(os.path.join(repo, "plugins", fixture.PLUGIN_ID, "featured.json"),
                       {"schema": 1, "featured": [{"plugin": fixture.PLUGIN_ID}]})


def the_featured_list_edited_without_approval(repo, ctx):
    """Which plugins go in the window is an editorial decision, and only a maintainer takes it. The
    label is how they say so — the same mechanism a key rotation and a verification go through."""
    document = _featured(repo)
    document["featured"][0]["note"] = "moved to the top after a fortnight of installs"
    _write_featured(repo, document)


def a_window_pointing_at_a_plugin_that_does_not_exist(repo, ctx):
    document = _featured(repo)
    document["featured"][0]["plugin"] = "invalid.example.nothing"
    _write_featured(repo, document)


def a_window_pointing_at_a_plugin_with_every_version_withdrawn(repo, ctx):
    """The subtle one: the plugin exists, the id resolves, the row is in the catalogue — and there is
    nothing behind it anybody can install. A window with an empty box in it, and the person who
    follows it concludes the store is broken rather than the list."""
    plugin = _plugin(repo)
    for version in plugin["versions"]:
        version["withdrawn"] = {"at": "2026-09-01", "reason": "a fault nobody should be installing"}
    _write_plugin(repo, plugin)


def the_same_plugin_featured_twice(repo, ctx):
    document = _featured(repo)
    document["featured"].append({"plugin": fixture.PLUGIN_ID})
    _write_featured(repo, document)


def spotlit_and_featured_at_once(repo, ctx):
    """One plugin in two places in one window. Resolving it quietly would hide that somebody edited
    the list without reading it, which is the fault worth surfacing rather than the duplicate row."""
    document = _featured(repo)
    document["spotlight"] = fixture.featured_spotlight()
    _write_featured(repo, document)


def a_window_with_everything_in_it(repo, ctx):
    """Past some length featuring stops distinguishing anything and becomes a second copy of the
    catalogue in an order nobody chose."""
    document = _featured(repo)
    document["featured"] = [{"plugin": fixture.PLUGIN_ID}] * 13
    _write_featured(repo, document)


def a_tier_smuggled_into_the_featured_list(repo, ctx):
    """**The blur this whole design exists to make unspellable.**

    Featuring is editorial and a tier is evidential, and the one place somebody could quietly hand
    themselves the second while writing the first is a field on a featured row. There is no such
    field and the schema is closed, so this is a schema failure rather than a value that gets
    published because nothing looked at it.
    """
    document = _featured(repo)
    document["featured"][0]["tier"] = "verified"
    _write_featured(repo, document)


def a_spotlight_with_nothing_said_about_it(repo, ctx):
    """The blurb is required. Spotlighting something is publishing our prose beside a stranger's
    binary, and a spotlight with no sentence is the whole of that weight with none of the thought."""
    document = _featured(repo)
    document["featured"] = []
    document["spotlight"] = fixture.featured_spotlight()
    del document["spotlight"]["blurb"]
    _write_featured(repo, document)


def something_else_in_the_curation_directory(repo, ctx):
    with open(os.path.join(repo, "curation", "featured.backup.json"), "w", encoding="utf-8") as handle:
        handle.write('{"schema": 1, "featured": []}')


# ---- and the editorial changes that are allowed ----------------------------------------------


def the_window_rearranged(repo, ctx):
    """A maintainer reordering the list. With the label this passes — and it has to be watched
    passing, because a check that only ever refuses is a check nobody can tell from a blanket
    denial. This is the happy case for the whole feature: it is what the cloud admin console opens
    a pull request to do."""
    document = _featured(repo)
    document["featured"] = []
    document["spotlight"] = fixture.featured_spotlight()
    _write_featured(repo, document)


def the_window_emptied(repo, ctx):
    """Nothing featured, said out loud. An empty window is a window, and it is what this registry is
    in today — so it must not be mistaken for a broken file."""
    _write_featured(repo, {"schema": 1, "updatedAt": "2026-09-01", "featured": []})


SCENARIOS = [
    # (name, mutation, expected code)
    ("an unknown field in the manifest", unknown_field, "SCHEMA_INVALID"),
    ("a required field left out", missing_required_field, "SCHEMA_INVALID"),
    ("a version that is not semver", not_semver, "SCHEMA_INVALID"),
    ("an id that does not match its directory", id_does_not_match_directory, "LAYOUT_DIR_ID_MISMATCH"),
    ("two manifests claiming one id", duplicate_id, "ID_DUPLICATE"),
    ("the same version declared twice", duplicate_version, "VERSION_DUPLICATE"),
    ("a publisher with no record", unknown_publisher, "PUBLISHER_UNKNOWN"),
    ("a plugin handed to a different publisher", publisher_reassigned, "PUBLISHER_REASSIGNED"),
    ("a key id the publisher has never had", key_not_pinned, "KEY_UNKNOWN"),
    ("an update signed by somebody else's key", signed_by_another_key, "SIGNATURE_INVALID"),
    ("the pinned public key swapped out", pinned_key_swapped, "KEY_MUTATED"),
    ("the pinned key deleted and replaced", pinned_key_deleted, "KEY_MUTATED"),
    ("a second key added with no rotation approval", key_added_without_approval, "KEY_ROTATION_UNAPPROVED"),
    ("a revoked key signing a new release", revoked_key_signs, "KEY_REVOKED"),
    ("a published version edited afterwards", published_version_edited, "VERSION_MUTATED"),
    ("a published version deleted", published_version_removed, "VERSION_REMOVED"),
    ("a download URL that does not resolve", url_does_not_resolve, "URL_UNRESOLVED"),
    ("a SHA-256 that does not match the bytes", digest_does_not_match, "SHA256_MISMATCH"),
    ("a size that does not match the bytes", size_does_not_match, "SIZE_MISMATCH"),
    ("an archive past the size budget", over_size_budget, "SIZE_BUDGET"),
    ("an abi this registry does not carry", abi_from_the_future, "ABI_UNSUPPORTED"),
    ("an architecture missing with no reason", architecture_silently_missing, "RID_COVERAGE"),
    ("an archive whose plugin.json disagrees", archive_disagrees_with_submission, "ARCHIVE_MANIFEST_MISMATCH"),
    ("an archive with no plugin.json", archive_has_no_manifest, "ARCHIVE_MALFORMED"),
    ("an archive with nothing to launch", archive_has_nothing_to_launch, "ARCHIVE_MALFORMED"),
    ("an archive that is not a tarball", archive_is_not_a_tarball, "ARCHIVE_MALFORMED"),
    ("a source link that does not resolve", source_does_not_resolve, "SOURCE_UNRESOLVED"),
    ("a licence the registry does not carry", licence_not_carried, "LICENSE_NOT_ALLOWED"),
    ("an artifact committed into the registry", artifact_committed_to_the_registry, "LAYOUT_UNEXPECTED_FILE"),

    # Tiers. The first two are the self-claim; the rest are a maintainer's record being wrong.
    ("a plugin claiming its own tier", tier_claimed_in_a_plugin_manifest, "SCHEMA_INVALID"),
    ("a publisher claiming their own tier", tier_claimed_in_a_publisher_record, "SCHEMA_INVALID"),
    ("a verification nobody approved", verification_written_without_approval, "VERIFICATION_UNAPPROVED"),
    ("evidence at a URL the submitter chose", evidence_at_a_url_the_submitter_chose,
     "VERIFICATION_EVIDENCE_MISPLACED"),
    ("a verification for a publisher with no record", verification_for_a_publisher_with_no_record,
     "PUBLISHER_UNKNOWN"),
    ("a verification named for another publisher", verification_named_for_another_publisher,
     "VERIFICATION_ID_MISMATCH"),
    ("official claimed by a verification record", official_claimed_by_a_verification, "SCHEMA_INVALID"),
    ("a tier that does not exist", a_tier_that_does_not_exist, "SCHEMA_INVALID"),
    ("a verification quietly deleted", verification_quietly_deleted, "VERIFICATION_REMOVED"),
    ("a verification record for a publisher who is already official",
     official_publisher_given_a_verification_record, "VERIFICATION_REDUNDANT"),
    ("a stray file in verification/", something_else_in_the_verification_directory, "LAYOUT_UNEXPECTED_FILE"),

    # Featuring. The first three are the self-claim — the thing a submitter would most like to write
    # — and the rest are a maintainer's own list being wrong.
    ("a plugin featuring itself", a_plugin_featuring_itself, "SCHEMA_INVALID"),
    ("a plugin spotlighting itself", a_plugin_spotlighting_itself, "SCHEMA_INVALID"),
    ("a featured list dropped beside a manifest", a_featured_list_beside_a_manifest,
     "LAYOUT_UNEXPECTED_FILE"),
    ("the featured list edited with nobody's approval", the_featured_list_edited_without_approval,
     "CURATION_UNAPPROVED"),
    ("a window pointing at a plugin that does not exist",
     a_window_pointing_at_a_plugin_that_does_not_exist, "CURATION_UNKNOWN_PLUGIN"),
    ("a window pointing at a plugin with every version withdrawn",
     a_window_pointing_at_a_plugin_with_every_version_withdrawn, "CURATION_NOTHING_OFFERED"),
    ("the same plugin featured twice", the_same_plugin_featured_twice, "CURATION_DUPLICATE"),
    ("one plugin both spotlit and featured", spotlit_and_featured_at_once, "CURATION_DUPLICATE"),
    ("a window with everything in it", a_window_with_everything_in_it, "CURATION_TOO_MANY"),
    ("a tier smuggled into the featured list", a_tier_smuggled_into_the_featured_list, "SCHEMA_INVALID"),
    ("a spotlight with nothing said about it", a_spotlight_with_nothing_said_about_it, "SCHEMA_INVALID"),
    ("a stray file in curation/", something_else_in_the_curation_directory, "LAYOUT_UNEXPECTED_FILE"),
]

# Things that look like sabotage and are actually allowed. Without these the suite would pass
# just as happily if the validator refused everything.
ACCEPTED = [
    ("an architecture declared unsupported, with a reason", architecture_declared_unsupported),
]


# ---------------------------------------------------------------------------------------------


class Run:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, description: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"  ok    {description}")
        else:
            self.failed.append(description)
            print(f"  FAIL  {description}")
            if detail:
                for line in detail.strip().splitlines():
                    print(f"          {line}")


def copy_repo(source: str, into: str) -> str:
    target = os.path.join(into, "repo")
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)
    return target


def main() -> int:
    run = Run()
    with tempfile.TemporaryDirectory(prefix="remaestro-registry-tests-") as scratch:
        ctx = fixture.build(scratch)
        server = fixture.Server(ctx["artifacts"])
        origin_map = server.origin_map
        try:
            print("\ncontrol — the clean registry, before anything is broken")
            outcome = run_validator(ctx["repo"], origin_map)
            run.check("a well-formed submission passes",
                      outcome.returncode == 0 and outcome.payload.get("ok") is True,
                      json.dumps(outcome.payload, indent=2) + outcome.stderr)
            if outcome.returncode != 0:
                print("\nthe control failed, so nothing below would mean anything. Stopping.")
                return 1

            print("\nsabotage — one rule at a time")
            work = os.path.join(scratch, "work")
            os.makedirs(work, exist_ok=True)
            for description, mutate, expected in SCENARIOS:
                repo = copy_repo(ctx["repo"], work)
                mutate(repo, ctx)
                outcome = run_validator(repo, origin_map)
                ok = outcome.returncode == 1 and expected in outcome.codes
                run.check(f"{description} → {expected}", ok,
                          f"exit {outcome.returncode}, codes {outcome.codes}\n{outcome.stderr}")

            print("\ncounter-controls — things that must still be allowed")
            for description, mutate in ACCEPTED:
                repo = copy_repo(ctx["repo"], work)
                mutate(repo, ctx)
                outcome = run_validator(repo, origin_map)
                run.check(f"{description} → passes", outcome.returncode == 0,
                          json.dumps(outcome.payload, indent=2))

            repo = copy_repo(ctx["repo"], work)
            key_added_without_approval(repo, ctx)
            outcome = run_validator(repo, origin_map, allow_rotation=True)
            run.check("a key rotation with the label → passes", outcome.returncode == 0,
                      json.dumps(outcome.payload, indent=2))

            print("\nverification — who may write one, and what has to still be true")
            for description, mutate in (
                ("a verification re-checked, with the label", verification_rechecked),
                ("a verification withdrawn rather than deleted", verification_withdrawn),
            ):
                repo = copy_repo(ctx["repo"], work)
                mutate(repo, ctx)
                outcome = run_validator(repo, origin_map, allow_verification=True)
                run.check(f"{description} → passes", outcome.returncode == 0,
                          json.dumps(outcome.payload, indent=2))

            # The evidence stops saying what it said. Both of these mutate the *served* document
            # rather than the registry, so each is restored afterwards — a leaked mutation here would
            # make every later check a check of the wrong world.
            for description, body, expected in (
                ("evidence that names somebody else", f"{fixture.EVIDENCE_KEY}=invalid.somebody-else\n",
                 "VERIFICATION_EVIDENCE_UNPROVEN"),
                ("evidence that is a page rather than the line", "<html><body>hello</body></html>\n",
                 "VERIFICATION_EVIDENCE_UNPROVEN"),
            ):
                fixture.write_evidence(ctx["artifacts"], body)
                try:
                    repo = copy_repo(ctx["repo"], work)
                    verification_rechecked(repo, ctx)
                    outcome = run_validator(repo, origin_map, allow_verification=True)
                    run.check(f"{description} → {expected}",
                              outcome.returncode == 1 and expected in outcome.codes,
                              f"exit {outcome.returncode}, codes {outcome.codes}")
                finally:
                    fixture.write_evidence(ctx["artifacts"], f"{fixture.EVIDENCE_KEY}={fixture.PUBLISHER_ID}\n")

            # And the document simply not being there — the papercut rather than the attack, and the
            # one whose message has to say more than "404".
            #
            # The same three-way split as an artifact that has gone missing: a pull request that does
            # not touch a verification says nothing about it, a pull request that does re-reads it,
            # and the scheduled audit re-reads all of them. A publisher's domain lapsing is exactly
            # the event that happens long after anybody opened a pull request.
            kept = fixture.evidence_file(ctx["artifacts"]) + ".moved"
            os.rename(fixture.evidence_file(ctx["artifacts"]), kept)
            try:
                repo = copy_repo(ctx["repo"], work)
                outcome = run_validator(repo, origin_map)
                run.check("a pull request does not re-read a verification it did not touch",
                          outcome.returncode == 0, json.dumps(outcome.payload, indent=2))

                outcome = run_validator(repo, origin_map, recheck_all=True)
                run.check("--recheck-all finds the evidence that has stopped resolving",
                          outcome.returncode == 1
                          and "VERIFICATION_EVIDENCE_UNRESOLVED" in outcome.codes,
                          f"exit {outcome.returncode}, codes {outcome.codes}")

                repo = copy_repo(ctx["repo"], work)
                verification_rechecked(repo, ctx)
                outcome = run_validator(repo, origin_map, allow_verification=True)
                run.check("evidence that was never published → VERIFICATION_EVIDENCE_UNRESOLVED",
                          outcome.returncode == 1
                          and "VERIFICATION_EVIDENCE_UNRESOLVED" in outcome.codes,
                          f"exit {outcome.returncode}, codes {outcome.codes}")
                run.check("and the refusal names the two usual causes rather than shrugging at a 404",
                          "never published" in outcome.message_for("VERIFICATION_EVIDENCE_UNRESOLVED"),
                          outcome.message_for("VERIFICATION_EVIDENCE_UNRESOLVED"))
            finally:
                os.rename(kept, fixture.evidence_file(ctx["artifacts"]))

            for description, condition, detail in _tier_checks():
                run.check(description, condition, detail)

            print("\nthe base ref is what makes half of this checkable")
            repo = copy_repo(ctx["repo"], work)
            published_version_edited(repo, ctx)
            outcome = run_validator(repo, origin_map, base_ref=None)
            run.check("without a base ref, an edit to a published version goes unnoticed "
                      "(so CI must always pass one)",
                      outcome.returncode == 0 and any("no base ref" in n for n in outcome.payload["notes"]),
                      json.dumps(outcome.payload, indent=2))

            print("\nwhat a pull request fetches, and what only the scheduled audit does")
            # A published version's artifact quietly disappears. A pull request that does not touch
            # that version says nothing about it — deliberately, so a patch bump does not re-download
            # a publisher's whole back catalogue. The audit is what notices.
            vanished = os.path.join(ctx["artifacts"], "lamp-1.0.0-linux-arm64.tar.gz")
            kept = vanished + ".kept"
            os.rename(vanished, kept)
            try:
                repo = copy_repo(ctx["repo"], work)
                outcome = run_validator(repo, origin_map)
                run.check("a pull request does not re-fetch versions it did not touch",
                          outcome.returncode == 0, json.dumps(outcome.payload, indent=2))

                outcome = run_validator(repo, origin_map, recheck_all=True)
                run.check("--recheck-all finds the published artifact that has gone missing",
                          outcome.returncode == 1 and "URL_UNRESOLVED" in outcome.codes,
                          json.dumps(outcome.payload, indent=2))
            finally:
                os.rename(kept, vanished)

            print("\nfeaturing — who may fill the window, and what it is allowed to mean")
            for description, mutate in (
                ("the window rearranged, with the label", the_window_rearranged),
                ("the window emptied, with the label", the_window_emptied),
            ):
                repo = copy_repo(ctx["repo"], work)
                mutate(repo, ctx)
                outcome = run_validator(repo, origin_map, allow_curation=True)
                run.check(f"{description} → passes", outcome.returncode == 0,
                          json.dumps(outcome.payload, indent=2))

            # The counter-control for the label itself. Without this, `CURATION_UNAPPROVED` would go
            # on passing if the gate were inverted to refuse everything, or if `changed` were
            # computed as "always true" — which is exactly the shape the verification check was
            # written to avoid and is worth one check to hold.
            repo = copy_repo(ctx["repo"], work)
            outcome = run_validator(repo, origin_map)
            run.check("an untouched window needs no label", outcome.returncode == 0,
                      json.dumps(outcome.payload, indent=2))

            for description, condition, detail in _featuring_is_not_a_tier():
                run.check(description, condition, detail)

            print("\nthe index")
            run.check(*_index_checks(ctx, scratch))
            run.check(*_withdrawn_tier_check(ctx, scratch))
            for description, condition, detail in _featured_index_checks(ctx, scratch):
                run.check(description, condition, detail)
            for description, condition, detail in _signing_checks(ctx, scratch):
                run.check(description, condition, detail)

        finally:
            server.close()

    print()
    if run.failed:
        print(f"{len(run.failed)} of {run.passed + len(run.failed)} checks failed:")
        for description in run.failed:
            print(f"  - {description}")
        return 1
    print(f"all {run.passed} checks passed")
    return 0


def _tier_checks():
    """The resolution itself, and the fail-closed direction.

    Read directly rather than through a submission because the interesting cases are the ones with
    no valid record at all — a withdrawn one, a malformed one, a publisher nobody has looked at —
    and the point of every one of them is that they land on `unverified`. **Nothing fails upward.**
    A bug here that resolved a broken record to `verified` would be invisible in a registry whose
    records all happen to be well-formed, which is the same reason the sabotage suite exists.
    """

    from registry import policy, verification

    official = policy.OFFICIAL_PUBLISHERS[0]

    yield ("official comes from our own source and needs no record at all",
           verification.tier_of(official, {}) == "official", "")

    active = fixture.verification_record()
    yield ("an active verification is verified",
           verification.tier_of(fixture.PUBLISHER_ID, {fixture.PUBLISHER_ID: active}) == "verified", "")

    withdrawn = {**active, "status": "withdrawn"}
    unverifiable = [
        ("a publisher nobody has checked", {}),
        ("a withdrawn verification", {fixture.PUBLISHER_ID: withdrawn}),
        ("a record with no status at all", {fixture.PUBLISHER_ID: {"publisher": fixture.PUBLISHER_ID}}),
        ("a record about somebody else", {"invalid.other": active}),
    ]
    for description, found in unverifiable:
        yield (f"{description} → unverified",
               verification.tier_of(fixture.PUBLISHER_ID, found) == "unverified", "")

    # The evidence URL is computed from the id and from nothing else, which is the whole security
    # argument. Written out here rather than derived the way the code derives it: two copies of one
    # rule agree with each other whatever the rule says.
    yield ("the evidence URL is derived from the publisher id",
           verification.evidence_url("com.acme") == "https://acme.com/.well-known/remaestro-publisher.txt",
           verification.evidence_url("com.acme"))
    yield ("and a GitHub owner's id derives to their Pages host",
           verification.evidence_url("io.github.acme")
           == "https://acme.github.io/.well-known/remaestro-publisher.txt",
           verification.evidence_url("io.github.acme"))

    # Measured on 2026-08-18: a Pages site running default Jekyll drops dot-directories from its
    # output, so `.well-known/` is in the repository and not on the site. That failure is invisible
    # from the publisher's side, and a refusal that says only "404" sends them to check the one thing
    # that is fine.
    yield ("a GitHub Pages publisher is told about .nojekyll, because Jekyll hides .well-known",
           ".nojekyll" in verification.why_missing("io.github.acme"),
           verification.why_missing("io.github.acme"))
    yield ("and a publisher on their own domain is not told about a thing that cannot affect them",
           ".nojekyll" not in verification.why_missing("com.acme"),
           verification.why_missing("com.acme"))

    # **The sentence, in every document that introduces a tier.** A tier is the one thing here a
    # person would act on, and the act is running somebody's binary with the hub's own privileges. So
    # the denial travels with the claim, word for word, in the three places a publisher or a reader
    # meets it — and this asserts all three rather than one, because a disclaimer that survives in
    # the file nobody opens is a disclaimer that has been deleted.
    for name in ("README.md", "CONTRIBUTING.md", os.path.join("docs", "verification.md")):
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as handle:
            body = handle.read()
        yield (f"{name} says what a tier does not mean, in the same words as the others",
               TIER_DISCLAIMER in body, f"{name} does not carry: {TIER_DISCLAIMER}")


def _index_checks(ctx, scratch):
    import jsonschema

    out = os.path.join(scratch, "index")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tools"))
    result = subprocess.run(
        [sys.executable, "-m", "registry.build_index", "--repo", ctx["repo"], "--out", out,
         "--generated-at", "2026-08-15T00:00:00+00:00"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    if result.returncode != 0:
        return ("the index generates", False, result.stderr)

    document = fixture.read_json(os.path.join(out, "plugins", f"{fixture.PLUGIN_ID}.json"))
    catalogue = fixture.read_json(os.path.join(out, "catalog.json"))

    plugin_schema = fixture.read_json(os.path.join(ROOT, "schema", "index-plugin.schema.json"))
    catalog_schema = fixture.read_json(os.path.join(ROOT, "schema", "index-catalog.schema.json"))
    problems = []
    for schema, instance, label in ((plugin_schema, document, "per-plugin document"),
                                    (catalog_schema, catalogue, "catalogue")):
        for error in jsonschema.Draft202012Validator(schema).iter_errors(instance):
            problems.append(f"{label}: {'/'.join(str(p) for p in error.absolute_path)}: {error.message}")

    if document["latest"].get("1", {}).get("version") != "1.1.0":
        problems.append(f"latest for abi 1 is {document['latest'].get('1', {}).get('version')!r}, wanted 1.1.0")
    if catalogue["plugins"][0]["latestVersion"] != "1.1.0":
        problems.append("the catalogue disagrees with the per-plugin document about the newest version")

    # The tier, in both documents, because the console reads one to browse and the other to install
    # and a plugin that changes tier between the two screens is worse than one that carries neither.
    if document["publisher"].get("tier") != "verified":
        problems.append(f"the per-plugin document says tier {document['publisher'].get('tier')!r}")
    if catalogue["plugins"][0]["publisher"].get("tier") != "verified":
        problems.append(f"the catalogue says tier {catalogue['plugins'][0]['publisher'].get('tier')!r}")

    # And what was checked, where and when — in the document somebody is reading when they are about
    # to install, so a console can name the domain rather than draw a tick.
    checked = document["publisher"].get("verification")
    if not checked or checked.get("evidence") != fixture.EVIDENCE_URL:
        problems.append(f"the per-plugin document carries {checked!r} rather than the evidence that was read")

    return ("the generated index is schema-valid, offers the newest version per abi, and carries the tier",
            not problems, "\n".join(problems))


def _featuring_is_not_a_tier():
    """The properties that hold by construction, asserted against the real files rather than assumed.

    Every one of these is a thing somebody could undo in a one-line diff that no sabotage above would
    notice, because none of them changes what the validator refuses — they change what it is
    *possible* to write, which is the stronger guarantee and the quieter one to lose.
    """

    schema_dir = os.path.join(ROOT, "schema")
    featured = fixture.read_json(os.path.join(schema_dir, "featured.schema.json"))
    submission = fixture.read_json(os.path.join(schema_dir, "submission.schema.json"))
    install = fixture.read_json(os.path.join(schema_dir, "index-plugin.schema.json"))
    catalogue = fixture.read_json(os.path.join(schema_dir, "index-catalog.schema.json"))

    # Closed at every level, which is what makes "a tier smuggled into the featured list" a schema
    # failure rather than a field that rides along because nothing looked at it.
    open_levels = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                open_levels.append(path or "(root)")
            for key, value in node.items():
                walk(value, f"{path}/{key}" if path else key)
        elif isinstance(node, list):
            for n, value in enumerate(node):
                walk(value, f"{path}/{n}")

    walk(featured, "")
    yield ("every level of the featured schema refuses a field it does not know",
           not open_levels, "\n".join(open_levels))

    # The self-claim, made unspellable rather than merely refused.
    yield ("a submission has no field that reaches the window",
           submission.get("additionalProperties") is False
           and not {"featured", "spotlight"} & set(submission.get("properties", {})),
           json.dumps(sorted(submission.get("properties", {})), indent=2))

    # And the install document has nowhere to put one, so featuring cannot grow into a dependency
    # even by somebody deciding it would be convenient.
    yield ("the document a hub installs from has nowhere to put a window",
           install.get("additionalProperties") is False
           and not {"featured", "spotlight"} & set(install.get("properties", {})),
           json.dumps(sorted(install.get("properties", {})), indent=2))

    # The window carries an order and no judgement about anybody.
    window = catalogue.get("properties", {}).get("featured", {})
    fields = set(window.get("properties", {}))
    yield ("the published window carries an order and no tier",
           fields == {"spotlight", "plugins"}, json.dumps(sorted(fields), indent=2))

    # The number lives in one place. A limit copied into the schema as `maxItems` would be a second
    # copy that agrees with the first until somebody moves one.
    rows = featured.get("properties", {}).get("featured", {})
    yield ("the size of the window is a constant in policy.py and not a second copy in the schema",
           "maxItems" not in rows, json.dumps(rows, indent=2))

    for name in ("README.md", os.path.join("curation", "README.md"),
                 os.path.join("docs", "featured.md")):
        path = os.path.join(ROOT, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                body = handle.read()
        except OSError as error:
            yield (f"{name} carries the sentence that separates featuring from a tier", False, str(error))
            continue
        yield (f"{name} carries the sentence that separates featuring from a tier",
               FEATURED_DISCLAIMER in body, f"{path} does not contain it")


def _featured_index_checks(ctx, scratch):
    """Where the window lands, and — the load-bearing half — where it does not.

    `catalog.json` is browse and search and may grow; `plugins/<id>.json` is what a hub fetches to
    install and is kept small on purpose. Featuring is published to the first and to nothing else,
    which is what makes *"a hub that never reads the catalogue installs exactly what it would have
    installed anyway"* a fact about the file layout rather than a paragraph somebody wrote. So the
    second assertion here is not a tidiness check: it is the whole guarantee, and it would go on
    passing silently if it were only ever asserted about a registry with nothing featured.
    """

    out = os.path.join(scratch, "index-featured")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tools"))

    def build(repo):
        result = subprocess.run(
            [sys.executable, "-m", "registry.build_index", "--repo", repo, "--out", out,
             "--generated-at", "2026-08-15T00:00:00+00:00"],
            capture_output=True, text=True, env=env, cwd=ROOT)
        return result

    result = build(ctx["repo"])
    if result.returncode != 0:
        yield ("the index generates with a window in it", False, result.stderr)
        return

    catalogue = fixture.read_json(os.path.join(out, "catalog.json"))
    document = fixture.read_json(os.path.join(out, "plugins", f"{fixture.PLUGIN_ID}.json"))

    window = catalogue.get("featured")
    yield ("the browse catalogue carries the window it was given",
           isinstance(window, dict) and window.get("plugins") == [fixture.PLUGIN_ID],
           json.dumps(window, indent=2))

    # The one that matters. Asserted over the whole document rather than over a named field, so a
    # future generator that publishes it under some other name fails here rather than shipping.
    leaked = [key for key in ("featured", "spotlight") if key in document]
    yield ("the install document carries no window, under any name",
           not leaked and "featured" not in json.dumps(document),
           f"the per-plugin document contains {leaked!r}")

    # The note is ours, and it stays ours. The fixture's row carries one on purpose: over an empty
    # list this assertion is true of nothing, and a sabotage that published every note was watched
    # passing here for exactly that reason before the fixture grew a row.
    yield ("a maintainer's private note is not published",
           "the only thing published so far" not in json.dumps(window)
           and "note" not in json.dumps(window),
           json.dumps(window, indent=2))

    work = os.path.join(scratch, "work")
    os.makedirs(work, exist_ok=True)

    # The spotlight, which is the one line of ours that is meant to be read.
    repo = copy_repo(ctx["repo"], work)
    fixture.write_json(fixture.featured_path(repo),
                       {"schema": 1, "featured": [], "spotlight": fixture.featured_spotlight()})
    result = build(repo)
    if result.returncode != 0:
        yield ("the index generates with a spotlight in it", False, result.stderr)
        return
    window = fixture.read_json(os.path.join(out, "catalog.json")).get("featured", {})
    yield ("the spotlight is published with the sentence somebody wrote for it",
           window.get("spotlight", {}).get("id") == fixture.PLUGIN_ID
           and "Talks to the bridge" in window.get("spotlight", {}).get("blurb", ""),
           json.dumps(window, indent=2))

    # And the generator's own belt: an id the catalogue does not carry is dropped rather than
    # published as a link into our own 404. The validator refuses this on a pull request, so the
    # only way to see it is to build over a tree the validator never saw.
    repo = copy_repo(ctx["repo"], work)
    fixture.write_json(fixture.featured_path(repo), {
        "schema": 1,
        "featured": [{"plugin": "invalid.example.nothing"}, {"plugin": fixture.PLUGIN_ID}],
    })
    result = build(repo)
    if result.returncode != 0:
        yield ("an index still generates over a window naming a plugin that is gone", False, result.stderr)
        return

    window = fixture.read_json(os.path.join(out, "catalog.json")).get("featured", {})
    yield ("a featured id with no row is dropped rather than published as a link into our own 404",
           window.get("plugins") == [fixture.PLUGIN_ID], json.dumps(window, indent=2))

    # Nothing featured is nothing published, rather than an empty block a console has to tell from
    # the absence of one.
    repo = copy_repo(ctx["repo"], work)
    os.remove(fixture.featured_path(repo))
    result = build(repo)
    empty = fixture.read_json(os.path.join(out, "catalog.json"))
    yield ("no featured list publishes no window at all, rather than an empty one",
           result.returncode == 0 and "featured" not in empty,
           json.dumps(empty.get("featured"), indent=2))


def _withdrawn_tier_check(ctx, scratch):
    """A withdrawn verification takes the tier with it, in both documents.

    The half a presence test cannot see. A registry that wrote `verified` from the *existence* of a
    record rather than from its status would pass every check above, and would go on telling every
    hub in the field that somebody is verified for exactly as long as the file sits there.
    """

    work = os.path.join(scratch, "withdrawn")
    repo = copy_repo(ctx["repo"], work)
    verification_withdrawn(repo, ctx)

    out = os.path.join(scratch, "index-withdrawn")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tools"))
    result = subprocess.run(
        [sys.executable, "-m", "registry.build_index", "--repo", repo, "--out", out,
         "--generated-at", "2026-08-18T00:00:00+00:00"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    if result.returncode != 0:
        return ("a withdrawn verification still generates an index", False, result.stderr)

    document = fixture.read_json(os.path.join(out, "plugins", f"{fixture.PLUGIN_ID}.json"))
    catalogue = fixture.read_json(os.path.join(out, "catalog.json"))

    problems = []
    if document["publisher"].get("tier") != "unverified":
        problems.append(f"the per-plugin document still says {document['publisher'].get('tier')!r}")
    if catalogue["plugins"][0]["publisher"].get("tier") != "unverified":
        problems.append(f"the catalogue still says {catalogue['plugins'][0]['publisher'].get('tier')!r}")
    if "verification" in document["publisher"]:
        problems.append("the evidence of a withdrawn verification is still published")

    return ("a withdrawn verification drops the publisher back to unverified in both documents",
            not problems, "\n".join(problems))


def _signing_checks(ctx, scratch):
    """The index signing step, proved with a throwaway key that exists only for this run."""

    out = os.path.join(scratch, "index")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tools"))
    subprocess.run([sys.executable, "-m", "registry.build_index", "--repo", ctx["repo"], "--out", out],
                   capture_output=True, text=True, env=env, cwd=ROOT, check=True)

    right = os.path.join(scratch, "index-key.pub")
    wrong = os.path.join(scratch, "wrong-index-key.pub")
    with open(right, "w", encoding="ascii") as handle:
        handle.write(ctx["index_key"].public_key)
    with open(wrong, "w", encoding="ascii") as handle:
        handle.write(ctx["wrong_index_key"].public_key)

    with open(ctx["index_key"].path, "r", encoding="ascii") as handle:
        key_pem = handle.read()

    signing_env = dict(os.environ, REGISTRY_INDEX_KEY_PEM=key_pem)
    good = subprocess.run(["bash", os.path.join(ROOT, "tools", "sign-index.sh"),
                           "--dir", out, "--verify-with", right],
                          capture_output=True, text=True, env=signing_env, cwd=ROOT)
    yield ("the index signs, and verifies against the key it was signed with",
           good.returncode == 0, good.stdout + good.stderr)

    signature_path = os.path.join(out, "catalog.json.sig")
    yield ("a .sig lands beside every document",
           os.path.isfile(signature_path) and os.path.isfile(
               os.path.join(out, "plugins", f"{fixture.PLUGIN_ID}.json.sig")),
           "")

    bad = subprocess.run(["bash", os.path.join(ROOT, "tools", "sign-index.sh"),
                          "--dir", out, "--verify-with", wrong],
                         capture_output=True, text=True, env=signing_env, cwd=ROOT)
    yield ("signing with the wrong generation of the key is refused rather than published",
           bad.returncode == 1, bad.stdout + bad.stderr)

    without_key = subprocess.run(["bash", os.path.join(ROOT, "tools", "sign-index.sh"), "--dir", out],
                                 capture_output=True, text=True,
                                 env={k: v for k, v in os.environ.items()
                                      if k != "REGISTRY_INDEX_KEY_PEM"}, cwd=ROOT)
    yield ("with no key in the environment it refuses, rather than looking for one on disk",
           without_key.returncode == 2, without_key.stdout + without_key.stderr)

    leaked = []
    for root, _, names in os.walk(out):
        for name in names:
            with open(os.path.join(root, name), "rb") as handle:
                if b"PRIVATE KEY" in handle.read():
                    leaked.append(os.path.join(root, name))
    yield ("no private key material is anywhere in the published output", not leaked, "\n".join(leaked))


if __name__ == "__main__":
    raise SystemExit(main())
