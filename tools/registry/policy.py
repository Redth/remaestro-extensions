"""Every number and list the registry judges a submission against, in one place.

Kept separate from the checks so that changing a limit is a one-line diff a reviewer can read,
and so the test suite can assert against the same constants the validator uses rather than
against copies of them.
"""

from __future__ import annotations

# The architectures the hub ships as, and therefore the only ones the registry carries.
# Anything else is a developer's laptop and is the SDK's local-run problem, not the registry's.
RIDS = ("linux-arm64", "linux-x64")

# The driver.proto protocol versions this registry will accept a submission for.
#
# `abi` is a single integer meaning "built against proto version N". The hub refuses a plugin
# from outside its own range with a sentence, before downloading anything.
#
# There is exactly one abi today and it does not exist yet: it is stamped by the version
# negotiation work that has to land before a single package is published. Until that ships,
# no submission can be honestly validated against it. See docs/manifest.md, "abi".
SUPPORTED_ABIS = (1,)

# Per-archive ceiling. The appliance's data partition is 3.0 GiB and does not grow; it already
# holds two app versions, the databases, the /etc overlay, certs, firmware and a whisper model.
# The budget for plugins is a few hundred megabytes in total, so a single archive that wants
# more than this is a conversation rather than a merge.
#
# For scale: a self-contained, single-file, trimmed .NET plugin measured 15.5 MB, and a Python
# plugin that vendors grpcio measures around 42 MB per architecture.
MAX_ARCHIVE_BYTES = 150 * 1024 * 1024

# Refuse to keep reading past this while streaming, whatever the manifest claimed. A declared
# size is the publisher's claim; this is ours.
HARD_DOWNLOAD_CEILING = MAX_ARCHIVE_BYTES + (8 * 1024 * 1024)

# Free licences only, and the list is short on purpose. Not because the others are bad, but
# because a paid plugin cannot be bought here today, so a licence that anticipates payment
# would be describing something that does not exist. Adding one is a one-line PR.
ALLOWED_LICENSES = (
    "0BSD",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "ISC",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "MIT",
    "MPL-2.0",
    "Unlicense",
    "Zlib",
)

# Seconds. A publisher's host being slow is not a reason to fail a PR forever, but a URL that
# takes longer than this to answer at all is one a hub on a domestic connection will struggle
# with too.
HTTP_TIMEOUT = 30

# The only signature algorithm, and it is the one the hub already verifies releases with:
# ECDSA P-256, SHA-256, DER-encoded, over the artifact bytes as received.
SIGNATURE_ALGORITHM = "ecdsa-p256-sha256"
