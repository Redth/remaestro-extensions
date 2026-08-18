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

# ---------------------------------------------------------------------------------------------
# Publisher tiers
#
# Three, and each says exactly one thing about *who a publisher is*:
#
#   official    published by us.
#   verified    somebody here checked that this publisher controls the name their id claims.
#   unverified  nobody checked. The name beside the plugin is a claim they made.
#
# **None of them says a plugin is safe, and none of them ever can.** Installing a plugin runs an
# arbitrary binary with the hub's own privileges; provenance is the only control that exists, and a
# tier is provenance about the *publisher* rather than about the code. A tier that reads as a safety
# claim is the one lie in this repository somebody would act on. See README.md.
TIERS = ("official", "verified", "unverified")

# The publisher ids this project publishes under. **This tuple is the whole of `official`** — it is
# not a field, not a label and not something a submission can carry, so there is no diff a stranger
# can open that puts them in it. Adding one is a change to our own source, reviewed like any other.
OFFICIAL_PUBLISHERS = ("app.remaestro",)

# How control of a name is shown. One method, and the reason there is only one is testability: the
# suite serves every byte from loopback through an origin map, and a DNS TXT check — the obvious
# alternative — could never be made to refuse anything in a test. A rule nobody has watched refuse
# something is not a rule, which is what tests/test_registry.py exists to say.
VERIFICATION_METHODS = ("well-known",)

# The document a publisher publishes to show they control the name. Its location is **derived from
# the publisher id** and never supplied by the submitter: an evidence URL somebody could choose is a
# check of whatever they chose to serve.
#
#   com.acme        -> https://acme.com/.well-known/remaestro-publisher.txt
#   io.github.acme  -> https://acme.github.io/.well-known/remaestro-publisher.txt
#
# The second is GitHub Pages for that owner, so one rule covers a domain and a GitHub account
# without a second method and without the GitHub API, whose 60-requests-an-hour ceiling is shared by
# every runner on a cloud provider.
WELL_KNOWN_PATH = "/.well-known/remaestro-publisher.txt"

# The line that document must carry. Exact, so a page that merely mentions a publisher id in prose
# is not evidence of anything.
WELL_KNOWN_KEY = "remaestro-publisher"

# Evidence is a line of text. Anything larger is a page that happens to be served there, and reading
# it is somebody else choosing how much of our runner's memory to use.
MAX_EVIDENCE_BYTES = 64 * 1024

# ---------------------------------------------------------------------------------------------
# Featuring
#
# **Editorial, and never evidential.** A tier records something somebody checked and is refused
# unless the evidence still resolves at a derived URL. Featuring records something somebody
# *decided*, and there is nothing to check — which is exactly why it is kept in its own file, under
# its own label, and published only to the browse catalogue. See tools/registry/curation.py.
#
# It is not a tier, it is not a badge, and it must never be rendered as either. "We put this in the
# window" and "we checked who publishes this" are different sentences, and the second is the one
# somebody would act on.

# How many plugins the window holds. A window with everything in it is a window with nothing in it:
# past some length, featuring stops distinguishing anything and becomes a second copy of the
# catalogue in an arbitrary order. Twelve is a browse row on a phone and a grid on a console.
MAX_FEATURED = 12
