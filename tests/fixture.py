"""Builds a small but complete registry, and the artifacts it points at, in a temporary directory.

Nothing here is committed to this repository — not a key, not a tarball, not a signature. The
keypairs are generated at test time into a directory that is deleted afterwards, which is the only
way to exercise the signature rules honestly: a check that has never verified a real signature and
never rejected a wrong one is not a check.

The artifacts are served over loopback by the test run itself. The manifests point at
`example.invalid`, which RFC 2606 reserves and which cannot resolve, and an origin map rewrites
that host to the local server. So a test that loses its map fails by failing to connect, rather
than by reaching something real — the network is never touched either way.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import tarfile
import threading

ARTIFACT_ORIGIN = "https://artifacts.example.invalid"

PUBLISHER_ID = "com.example"
PLUGIN_ID = "com.example.lamp"
KEY_ID = "2026-01"
RIDS = ("linux-arm64", "linux-x64")


def run(*args: str, cwd: str | None = None, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


class Keypair:
    """An ECDSA P-256 keypair, on disk only inside the scratch directory the run deletes."""

    def __init__(self, scratch: str, name: str) -> None:
        self.path = os.path.join(scratch, f"{name}.pem")
        run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", self.path)
        der = run("openssl", "ec", "-in", self.path, "-pubout", "-outform", "DER")
        self.public_key = base64.b64encode(der).decode("ascii")

    def public_pem_path(self) -> str:
        out = self.path.replace(".pem", ".pub.pem")
        run("openssl", "ec", "-in", self.path, "-pubout", "-out", out)
        return out

    def sign_file(self, path: str) -> str:
        der = run("openssl", "dgst", "-sha256", "-sign", self.path, path)
        return base64.b64encode(der).decode("ascii")


def make_archive(path: str, *, plugin_id: str, version: str, abi: int, rid: str,
                 include_manifest: bool = True, exec_argv=("./lamp",),
                 payload: bytes = b"#!/bin/sh\nexit 0\n") -> None:
    """A gzipped tar shaped like a real plugin: an entrypoint and a plugin.json beside it."""

    with tarfile.open(path, "w:gz") as tar:
        if include_manifest:
            manifest = {
                "id": plugin_id,
                "version": version,
                "abi": abi,
                "kind": "driver",
                "runtime": "native",
                "rid": rid,
            }
            if exec_argv is not None:
                manifest["exec"] = list(exec_argv)
            body = json.dumps(manifest, indent=2).encode("utf-8")
            info = tarfile.TarInfo("plugin.json")
            info.size = len(body)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(body))

        info = tarfile.TarInfo("lamp")
        info.size = len(payload)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(payload))


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Server:
    """Serves the artifact directory on loopback. Real HTTP, real bytes, no network."""

    def __init__(self, directory: str) -> None:
        handler = functools.partial(_QuietHandler, directory=directory)
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def origin_map(self) -> str:
        return f"{ARTIFACT_ORIGIN}=http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102
        pass


def build(scratch: str) -> dict:
    """Lays out the artifacts, the keys and a git repository whose HEAD is 'already published'.

    HEAD holds version 1.0.0. The working tree adds 1.1.0. That is what a real pull request looks
    like, and it is the only arrangement in which pinning, reassignment and edits-after-publication
    can be checked at all.
    """

    artifacts = os.path.join(scratch, "artifacts")
    os.makedirs(os.path.join(artifacts, "source"), exist_ok=True)
    with open(os.path.join(artifacts, "source", "lamp"), "w", encoding="utf-8") as handle:
        handle.write("a stand-in for the plugin's source repository\n")

    keys = os.path.join(scratch, "keys")
    os.makedirs(keys, exist_ok=True)
    publisher_key = Keypair(keys, "publisher")
    impostor_key = Keypair(keys, "impostor")
    index_key = Keypair(keys, "index")
    wrong_index_key = Keypair(keys, "wrong-index")

    archives: dict[str, dict] = {}
    for version in ("1.0.0", "1.1.0"):
        for rid in RIDS:
            name = f"lamp-{version}-{rid}.tar.gz"
            path = os.path.join(artifacts, name)
            make_archive(path, plugin_id=PLUGIN_ID, version=version, abi=1, rid=rid)
            archives[f"{version}/{rid}"] = {
                "url": f"{ARTIFACT_ORIGIN}/{name}",
                "sha256": sha256_of(path),
                "size": os.path.getsize(path),
                "signature": publisher_key.sign_file(path),
                "keyId": KEY_ID,
            }

    # Extra artifacts the sabotage scenarios point at. Built here so every one of them is a real
    # file a real server really serves — a sabotage that fails because the URL was invented would
    # look exactly like the check working.
    extras: dict[str, dict] = {}

    def extra(name: str, build_it, signer=publisher_key) -> None:
        path = os.path.join(artifacts, name)
        build_it(path)
        extras[name] = {
            "url": f"{ARTIFACT_ORIGIN}/{name}",
            "sha256": sha256_of(path),
            "size": os.path.getsize(path),
            "signature": signer.sign_file(path),
            "keyId": KEY_ID,
        }

    # A perfectly good rebuild of an *already published* version: valid tar, right embedded
    # manifest, correctly signed by the pinned key, different bytes. Every content check passes
    # on it. Repointing 1.0.0 at it is the swap that only the base ref can see.
    extra("lamp-1.0.0-linux-x64-rebuilt.tar.gz",
          lambda p: make_archive(p, plugin_id=PLUGIN_ID, version="1.0.0", abi=1, rid="linux-x64",
                                 payload=b"#!/bin/sh\n# rebuilt, and not the bytes anyone approved\nexit 0\n"))
    extra("lamp-1.1.0-wrong-version-inside.tar.gz",
          lambda p: make_archive(p, plugin_id=PLUGIN_ID, version="9.9.9", abi=1, rid="linux-arm64"))
    extra("lamp-1.1.0-no-manifest.tar.gz",
          lambda p: make_archive(p, plugin_id=PLUGIN_ID, version="1.1.0", abi=1, rid="linux-arm64",
                                 include_manifest=False))
    extra("lamp-1.1.0-no-exec.tar.gz",
          lambda p: make_archive(p, plugin_id=PLUGIN_ID, version="1.1.0", abi=1, rid="linux-arm64",
                                 exec_argv=None))
    extra("lamp-1.1.0-not-a-tarball.tar.gz",
          lambda p: open(p, "wb").write(b"this is not a gzipped tar, it is a sentence"))
    # Byte-identical to the real arm64 archive, signed by a key the publisher has never had.
    extra("lamp-1.1.0-impostor.tar.gz",
          lambda p: make_archive(p, plugin_id=PLUGIN_ID, version="1.1.0", abi=1, rid="linux-arm64"),
          signer=impostor_key)

    repo = os.path.join(scratch, "registry")
    _lay_out_repo(repo, publisher_key, archives)

    return {
        "repo": repo,
        "artifacts": artifacts,
        "archives": archives,
        "extras": extras,
        "publisher_key": publisher_key,
        "impostor_key": impostor_key,
        "index_key": index_key,
        "wrong_index_key": wrong_index_key,
    }


def _lay_out_repo(repo: str, publisher_key: Keypair, archives: dict) -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(repo, exist_ok=True)
    shutil.copytree(os.path.join(here, "schema"), os.path.join(repo, "schema"))
    shutil.copytree(os.path.join(here, "tools"), os.path.join(repo, "tools"))
    os.makedirs(os.path.join(repo, "publishers"), exist_ok=True)
    os.makedirs(os.path.join(repo, "plugins", PLUGIN_ID), exist_ok=True)

    write_json(os.path.join(repo, "publishers", f"{PUBLISHER_ID}.json"), {
        "id": PUBLISHER_ID,
        "name": "Example Publisher",
        "contact": "https://github.com/example",
        "keys": [{
            "id": KEY_ID,
            "algorithm": "ecdsa-p256-sha256",
            "publicKey": publisher_key.public_key,
            "addedAt": "2026-01-04",
            "status": "active",
        }],
    })

    write_json(plugin_path(repo), plugin_manifest(archives, versions=("1.0.0",)))

    run("git", "init", "-q", "-b", "main", repo)
    run("git", "-C", repo, "config", "user.email", "tests@example.invalid")
    run("git", "-C", repo, "config", "user.name", "registry tests")
    run("git", "-C", repo, "add", "-A")
    run("git", "-C", repo, "commit", "-q", "-m", "the registry as already published")

    # The pull request under test: one new version.
    write_json(plugin_path(repo), plugin_manifest(archives, versions=("1.0.0", "1.1.0")))


def plugin_path(repo: str) -> str:
    return os.path.join(repo, "plugins", PLUGIN_ID, "plugin.json")


def publisher_path(repo: str) -> str:
    return os.path.join(repo, "publishers", f"{PUBLISHER_ID}.json")


def plugin_manifest(archives: dict, versions=("1.0.0", "1.1.0")) -> dict:
    return {
        "id": PLUGIN_ID,
        "name": "Example Lamp",
        "summary": "Turns an example lamp on and off.",
        "publisher": PUBLISHER_ID,
        "kind": "driver",
        "license": "MIT",
        "source": f"{ARTIFACT_ORIGIN}/source/lamp",
        "versions": [
            {
                "version": version,
                "abi": 1,
                "runtime": "native",
                "releasedAt": "2026-01-05",
                "archives": {rid: dict(archives[f"{version}/{rid}"]) for rid in RIDS},
            }
            for version in versions
        ],
    }


def write_json(path: str, document: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
