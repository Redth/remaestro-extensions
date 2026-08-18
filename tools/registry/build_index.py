"""Turns the submissions into the documents a hub actually fetches.

Two documents, and the split is not tidiness.

`index/plugins/<id>.json` is the **install path**. It carries the newest offered version for each
abi and nothing else, because the update manifest this registry is modelled on refuses to be a
growing list on purpose: *"a document that grows with every release is a document that eventually
fails to parse on the oldest box in the field — the one that most needs to be able to update."*
Keying by abi rather than truncating to "the newest" keeps a hub that speaks an older protocol
able to find something, which a plain "latest" would not.

`index/catalog.json` is the **browse index**. It is allowed to grow, because the console's search
is the only thing that reads it and no install or update depends on it.

Both are signed. Only the first signature is load-bearing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import curation, verification
from .validate import load_json


def _semver_key(version: str):
    core, _, rest = version.partition("+")
    core, _, prerelease = core.partition("-")
    numbers = tuple(int(part) for part in core.split("."))
    # A release outranks any prerelease of the same core; between prereleases, compare parts.
    if not prerelease:
        return (numbers, 1, ())
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in prerelease.split("."))
    return (numbers, 0, parts)


def build(repo: str, generated_at: str | None = None) -> tuple[dict[str, dict], dict]:
    stamp = generated_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    publishers: dict[str, dict] = {}
    for name in sorted(os.listdir(os.path.join(repo, "publishers"))):
        if not name.endswith(".json"):
            continue
        document, problem = load_json(os.path.join(repo, "publishers", name))
        if problem is not None:
            raise SystemExit(f"publishers/{name}: {problem}")
        publishers[document["id"]] = document

    # Tiers are resolved here rather than carried in a submission, because no document a publisher
    # writes is allowed to say what tier they are in. `official` comes from a tuple in our own source
    # and `verified` from a maintainer-written record; everything else is `unverified`, including
    # every way this can go wrong. See registry/verification.py.
    verifications = verification.records(repo)

    documents: dict[str, dict] = {}
    catalogue: list[dict] = []

    plugins_dir = os.path.join(repo, "plugins")
    for entry in sorted(os.listdir(plugins_dir)):
        manifest_path = os.path.join(plugins_dir, entry, "plugin.json")
        if not os.path.isfile(manifest_path):
            continue
        plugin, problem = load_json(manifest_path)
        if problem is not None:
            raise SystemExit(f"plugins/{entry}/plugin.json: {problem}")

        publisher = publishers[plugin["publisher"]]
        tier = verification.tier_of(publisher["id"], verifications)
        checked = verification.published(verifications.get(publisher["id"]))

        latest: dict[str, dict] = {}
        withdrawn: list[dict] = []
        for version in plugin["versions"]:
            if "withdrawn" in version:
                withdrawn.append({
                    "version": version["version"],
                    "at": version["withdrawn"]["at"],
                    "reason": version["withdrawn"]["reason"],
                })
                continue
            abi = str(version["abi"])
            current = latest.get(abi)
            if current is None or _semver_key(version["version"]) > _semver_key(current["version"]):
                offered = {
                    "version": version["version"],
                    "abi": version["abi"],
                    "runtime": version["runtime"],
                    "releasedAt": version["releasedAt"],
                    "archives": version["archives"],
                }
                for optional in ("sourceCommit", "notes", "unsupportedRids"):
                    if optional in version:
                        offered[optional] = version[optional]
                latest[abi] = offered

        document = {
            "schema": 1,
            "id": plugin["id"],
            "name": plugin["name"],
            "summary": plugin["summary"],
            "license": plugin["license"],
            "source": plugin["source"],
            "kind": plugin["kind"],
            "publisher": {
                "id": publisher["id"],
                "name": publisher["name"],
                "contact": publisher["contact"],
                # Always written, never omitted — a hub that has to infer "unverified" from a missing
                # field is a hub one bug away from inferring something better instead.
                "tier": tier,
                # Every pinned key, revoked ones included. A hub that meets an archive signed by a
                # revoked key has to be able to say which key, not just that something is wrong.
                "keys": [
                    {"id": k["id"], "algorithm": k["algorithm"], "publicKey": k["publicKey"], "status": k["status"]}
                    for k in publisher["keys"]
                ],
            },
            "latest": latest,
            "withdrawn": withdrawn,
            "generatedAt": stamp,
        }
        # What was checked, where, and when — carried in the per-plugin document and not in the
        # catalogue. A console that says "the registry checked control of acme.com on 18 August 2026"
        # has given somebody a fact they can go and confirm; a tick has given them a feeling.
        if tier == "verified" and checked is not None:
            document["publisher"]["verification"] = checked

        for optional in ("description", "homepage", "tags"):
            if optional in plugin:
                document[optional] = plugin[optional]

        documents[plugin["id"]] = document

        offered_versions = [v for v in latest.values()]
        newest = max(offered_versions, key=lambda v: _semver_key(v["version"])) if offered_versions else None
        rids = sorted({rid for v in offered_versions for rid in v["archives"]})
        entry_row = {
            "id": plugin["id"],
            "name": plugin["name"],
            "summary": plugin["summary"],
            "kind": plugin["kind"],
            "license": plugin["license"],
            "source": plugin["source"],
            # The tier and nothing else about it: the browse list needs enough to draw a chip and to
            # filter, and the evidence a person would read before acting on it belongs on the path
            # that installs, which is the per-plugin document.
            "publisher": {"id": publisher["id"], "name": publisher["name"],
                          "contact": publisher["contact"], "tier": tier},
            "latestVersion": newest["version"] if newest else None,
            "abis": sorted(int(a) for a in latest),
            "rids": rids,
            "updatedAt": newest["releasedAt"] if newest else None,
            "document": f"plugins/{plugin['id']}.json",
        }
        for optional in ("homepage", "tags"):
            if optional in plugin:
                entry_row[optional] = plugin[optional]
        catalogue.append(entry_row)

    # The shop window, and it goes in the browse document **and nowhere else**.
    #
    # That is the whole of what keeps featuring from becoming load-bearing. `catalog.json` is browse
    # and search, and *"no install or update path may depend on it"*; `plugins/<id>.json` is what a
    # hub fetches to install. So a hub that never reads the catalogue — one that was sent a link,
    # one whose feed is unreachable, one browsing from a cache — installs exactly what it would have
    # installed anyway, because the document it reads has no field for this and
    # `additionalProperties: false` refuses to grow one. Written as a fact about the file layout
    # rather than as a promise in a paragraph, because a paragraph is not a check.
    #
    # Omitted entirely rather than written as an empty block: a console that has to tell "nothing is
    # featured" from "featured, and it is empty" has been given a distinction with no meaning.
    featured = curation.published(curation.load(repo), {row["id"] for row in catalogue})

    document = {"schema": 1, "generatedAt": stamp, "plugins": catalogue}
    if featured is not None:
        document["featured"] = featured
    return documents, document


def write(repo: str, out: str, generated_at: str | None = None) -> list[str]:
    documents, catalogue = build(repo, generated_at)
    os.makedirs(os.path.join(out, "plugins"), exist_ok=True)
    written: list[str] = []

    def dump(path: str, document: dict) -> None:
        # Sorted keys and a trailing newline, because these files are signed over their exact
        # bytes and a regeneration that reorders them is a signature that has to be redone.
        body = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        written.append(path)

    for plugin_id, document in sorted(documents.items()):
        dump(os.path.join(out, "plugins", f"{plugin_id}.json"), document)
    dump(os.path.join(out, "catalog.json"), catalogue)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the index a hub fetches.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default="index")
    parser.add_argument("--generated-at", default=None,
                        help="fix the timestamp, so a rebuild that changed nothing produces identical bytes")
    args = parser.parse_args(argv)

    written = write(os.path.abspath(args.repo), os.path.abspath(args.out), args.generated_at)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
