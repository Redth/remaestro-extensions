"""Fetching, hashing and signature checking — the half of validation that leaves the machine.

Two things here are deliberate rather than incidental.

**The origin map.** The test suite has to prove the URL, digest, size and signature checks
really fail when they should, and it cannot do that against the internet: a test that depends
on someone else's host is a test that goes red for someone else's reasons. So an origin map
rewrites a scheme+host prefix to a loopback server the suite runs itself. Real HTTP, real
bytes, real hashing, no network. CI passes no map, and says so in the workflow.

The fixtures use `example.invalid`, which is reserved by RFC 2606 and cannot resolve — so a
test that loses its map fails by not connecting, rather than by quietly reaching something.

**Signatures go through `openssl`.** Not because Python cannot do ECDSA with a library, but
because the hub verifies release manifests with `ECDsa.VerifyData(..., Rfc3279DerSequence)`
over a base64 SPKI, and `openssl dgst -verify` is the same operation with the same encodings.
One fewer place for the two halves to disagree about what a signature is.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable

from . import policy


class OriginMap:
    """Rewrites `https://host` prefixes. Empty in CI, populated by the test suite."""

    def __init__(self, pairs: Iterable[tuple[str, str]] = ()):  # noqa: D107
        self._pairs = [(a.rstrip("/"), b.rstrip("/")) for a, b in pairs]

    @classmethod
    def from_env(cls, raw: str | None) -> "OriginMap":
        """`REGISTRY_ORIGIN_MAP="https://a=http://127.0.0.1:1,https://b=http://127.0.0.1:2"`."""
        if not raw:
            return cls()
        pairs = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            source, _, target = chunk.partition("=")
            if not source or not target:
                raise ValueError(f"origin map entry is not 'from=to': {chunk!r}")
            pairs.append((source, target))
        return cls(pairs)

    def apply(self, url: str) -> str:
        for source, target in self._pairs:
            if url == source or url.startswith(source + "/"):
                return target + url[len(source):]
        return url

    def __bool__(self) -> bool:
        return bool(self._pairs)


@dataclass(frozen=True)
class Fetched:
    path: str
    sha256: str
    size: int


class FetchError(Exception):
    pass


def _open(url: str, method: str = "GET"):
    request = urllib.request.Request(url, method=method, headers={
        # A registry that identifies itself is one a publisher's host can allow deliberately.
        "User-Agent": "remaestro-extensions-validator/1",
        "Accept": "*/*",
    })
    return urllib.request.urlopen(request, timeout=policy.HTTP_TIMEOUT)


def resolves(url: str, origins: OriginMap) -> str | None:
    """None when the URL answers; otherwise why it did not, in words worth putting in a PR."""

    target = origins.apply(url)
    for method in ("HEAD", "GET"):
        try:
            with _open(target, method) as response:
                if 200 <= response.status < 300:
                    return None
                return f"{url} answered {response.status}"
        except urllib.error.HTTPError as error:
            # Plenty of hosts refuse HEAD and serve GET. Only a GET failure is a failure.
            if method == "HEAD" and error.code in (403, 405, 501):
                continue
            return f"{url} answered {error.code}"
        except urllib.error.URLError as error:
            return f"{url} did not resolve: {error.reason}"
        except (TimeoutError, OSError) as error:
            return f"{url} did not resolve: {error}"
    return f"{url} did not resolve"


def text(url: str, origins: OriginMap, limit: int) -> tuple[str | None, str | None]:
    """Read a small document as text. Returns (body, None) or (None, why not).

    Its own function rather than `download` with a decode, because what is being read here is a line
    of text somebody publishes to prove they control a name — not an artifact — and the failure worth
    reporting is different. A 404 on a publisher's own site is the ordinary case and needs a sentence
    a person can act on, which is the caller's job to write and this function's job not to swallow.
    """

    target = origins.apply(url)
    try:
        with _open(target) as response:
            body = response.read(limit + 1)
    except urllib.error.HTTPError as error:
        return None, f"{url} answered {error.code}"
    except urllib.error.URLError as error:
        return None, f"{url} did not resolve: {error.reason}"
    except (TimeoutError, OSError) as error:
        return None, f"{url} could not be read: {error}"

    if len(body) > limit:
        return None, f"{url} is larger than {limit} bytes, so it is a page rather than the one line expected"

    try:
        return body.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, f"{url} is not UTF-8"


def download(url: str, origins: OriginMap, into: str) -> Fetched:
    """Stream to a file, hashing as it goes, and stop dead if it runs long.

    The ceiling is checked while reading rather than afterwards, because "afterwards" means a
    runner that has already written a gigabyte somebody else chose.
    """

    target = origins.apply(url)
    digest = hashlib.sha256()
    size = 0
    path = os.path.join(into, "artifact.partial")

    try:
        with _open(target) as response:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > policy.HARD_DOWNLOAD_CEILING:
                raise FetchError(
                    f"{url} declares {int(declared)} bytes, past the {policy.HARD_DOWNLOAD_CEILING}-byte ceiling"
                )
            with open(path, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > policy.HARD_DOWNLOAD_CEILING:
                        raise FetchError(
                            f"{url} kept sending past the {policy.HARD_DOWNLOAD_CEILING}-byte ceiling"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
    except urllib.error.HTTPError as error:
        raise FetchError(f"{url} answered {error.code}") from error
    except urllib.error.URLError as error:
        raise FetchError(f"{url} did not resolve: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise FetchError(f"{url} could not be read: {error}") from error

    return Fetched(path=path, sha256=digest.hexdigest(), size=size)


def _pem(spki_base64: str) -> str:
    body = spki_base64.strip()
    wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{wrapped}\n-----END PUBLIC KEY-----\n"


def verify_signature(artifact_path: str, signature_base64: str, public_key_base64: str) -> str | None:
    """None when the signature is good, otherwise why it is not.

    Every failure shape ends up here — a signature made by a different key, a signature over
    different bytes, a value that is not a signature at all — and they are all the same answer
    to the submitter: these bytes were not signed by the key this publisher is pinned to.
    """

    if shutil.which("openssl") is None:
        return "openssl is not on PATH, so no signature could be checked"

    try:
        signature = base64.b64decode(signature_base64.strip(), validate=True)
    except Exception:
        return "the signature is not readable base64"
    if not signature:
        return "the signature is empty"

    try:
        base64.b64decode(public_key_base64.strip(), validate=True)
    except Exception:
        return "the pinned public key is not readable base64"

    with tempfile.TemporaryDirectory() as scratch:
        key_path = os.path.join(scratch, "key.pem")
        signature_path = os.path.join(scratch, "sig.der")
        with open(key_path, "w", encoding="ascii") as handle:
            handle.write(_pem(public_key_base64))
        with open(signature_path, "wb") as handle:
            handle.write(signature)

        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", key_path, "-signature", signature_path, artifact_path],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "Verified OK" in result.stdout:
            return None
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = detail[-1] if detail else "no detail"
        return f"the signature does not verify against this publisher's pinned key ({reason})"
