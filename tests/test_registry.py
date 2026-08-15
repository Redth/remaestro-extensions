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

import fixture  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


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
                  allow_rotation: bool = False, recheck_all: bool = False) -> Outcome:
    args = [sys.executable, "-m", "registry.validate", "--repo", repo, "--json",
            "--origin-map", origin_map]
    if base_ref:
        args += ["--base-ref", base_ref]
    if allow_rotation:
        args.append("--allow-key-rotation")
    if recheck_all:
        args.append("--recheck-all")

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

            print("\nthe index")
            run.check(*_index_checks(ctx, scratch))
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

    return ("the generated index is schema-valid and offers the newest version per abi",
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
