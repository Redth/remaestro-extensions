# reMaestro extensions

The plugin registry for [reMaestro](https://remaestro.app). A plugin adds a device driver — a
television, a bridge, a thermostat, whatever you have that the hub does not already speak to — and it
can be written in any language that can serve gRPC.

This repository is the registry itself: one manifest per plugin, submitted by pull request, checked
by CI, and published as a small signed index that a hub fetches. **The artifacts live in each
publisher's own storage.** Nothing here is a binary; every file is a name, a URL, a digest and a
signature.

---

## Read this before you install anything

**Installing a plugin runs an arbitrary binary on your hub, with the hub's own privileges. No
packaging, signing or marketplace choice changes that.**

Concretely, on a reMaestro appliance a plugin process runs as the hub's user with access to the whole
of `/var/lib/remaestro` — every database, every credential the hub stores, the TLS private key. In a
Docker install it is worse: the hub runs as root with host networking, and so does anything it
launches. There is no sandbox, no capability grant and no permission prompt, because a plugin is
trusted exactly as an in-repo driver is. That is a deliberate choice about what reMaestro is, not an
oversight, and it is the same choice that makes any-language plugins possible at all.

So **provenance is the only control that exists here.** Not the main one — the only one.

What this registry can honestly tell you before you install:

| | |
|---|---|
| These are the exact bytes the registry listed | **Yes.** A SHA-256 in a signed index, checked against what was downloaded. |
| This update came from whoever published the first version | **Yes.** Publisher keys are pinned on first publication. This is the highest-value signal here, and the console should say so loudly when it changes. |
| Who the publisher is | **A claim.** A name and a link they gave us. Nobody verifies identity. |
| Which source it says it was built from | **A link.** Recorded, and checked that it resolves. |
| That the binary matches that source | **No.** Only building it ourselves would show that, and we do not. |
| That the plugin is safe, or does what it says | **No.** Nothing static can tell you this, and under a trusted model a plugin can do anything the hub can. |

There is no verified badge here and there will not be one. A green tick over somebody else's binary
would be a claim we cannot make.

The counterweights are real, and they are about recovery rather than prevention: the hub can stop and
remove a plugin without its cooperation, plugin updates are **off by default and per plugin**, and
every plugin's publisher and source stay visible in the console permanently rather than only at
install.

---

## What review is, and is not

Every pull request is checked by CI **before a human looks**, so that reviewers spend their attention
on intent rather than on syntax. CI refuses a submission that has:

- a manifest that violates [the schema](schema/submission.schema.json), including any field we do not
  recognise;
- an `id` that is not reverse-DNS, does not match its directory, or is already somebody else's;
- a download URL that does not resolve, or a source link that does not;
- bytes whose **SHA-256** does not match what the manifest claims;
- an archive **not signed by a key that publisher was pinned to on their first publication**;
- a new key added to an existing publisher without a maintainer's explicit approval;
- an already-published version that has been edited, deleted, or repointed at different bytes;
- an archive whose own `plugin.json` disagrees with the submission, is missing, or has nothing to
  launch;
- an architecture silently missing, an unsupported `abi`, a licence we do not carry, or an archive
  past the size budget.

A person then reads the manifest, the description, the source repository and the diff. That is
roughly fifteen minutes for a new plugin and a glance for a version bump from a pinned key.

A pull request checks the bytes it is proposing, not every archive ever published — otherwise a patch
bump re-downloads every publisher's back catalogue. A [weekly audit](.github/workflows/audit.yml)
re-fetches and re-verifies everything, which is what notices an artifact that has quietly stopped
resolving or stopped matching its digest.

**It is not a security review.** Nobody audits a binary. It does not prove the binary matches the
source. It is not a promise the plugin works on your hardware, and nothing in this repository should
ever be worded as if it were.

A plugin can be **withdrawn** after publication. Your hub will tell you if you have a withdrawn
version installed; it will not remove it for you, and nothing here can. A channel that could delete
software from your house on our say-so would be a worse thing than the problem it solves.

---

## Installing

Two routes, and the second one owes this repository nothing:

- **From the registry.** The hub fetches a small signed document per plugin from
  `https://extensions.remaestro.app`, checks the digest and the publisher's signature, and installs.
  See [docs/index-format.md](docs/index-format.md).
- **From a URL.** Point the hub at any `plugin.json` and it installs, with no registry involved at
  all. This works when this repository is down, when you are offline from it, and when what you want
  is not listed here — including a plugin you are writing yourself.

The registry is discovery. It is never a dependency, and that is on purpose: the hub must never need
a service of ours to do anything.

---

## Publishing

Read [CONTRIBUTING.md](CONTRIBUTING.md). The short version: pick a reverse-DNS id, add
`publishers/<you>.json` with your public key, add `plugins/<id>/plugin.json`, open a pull request.

Detail lives in [docs/manifest.md](docs/manifest.md) (every field, and what it commits you to) and
[docs/signing.md](docs/signing.md) (keys, signatures, rotation).

---

## Layout

```
plugins/<id>/plugin.json      one submission per plugin — every version it has published
publishers/<id>.json          publisher records, including the pinned public keys
schema/                       JSON Schema for all four documents
keys/                         the public half of the index signing key
tools/registry/               the validator and the index generator
tools/sign-index.sh           the signing step
tests/test_registry.py        sabotages every rule above and watches CI refuse it
docs/                         the manifest, the index format, signing
index/                        generated and published by CI — not committed here
LICENSE                       MIT, and it covers this repository's own files and the manifests in it
```

Check a submission before you open a pull request:

```sh
pip install -r tools/requirements.txt
PYTHONPATH=tools python -m registry.validate --repo . --base-ref origin/main
```

---

## Status

**Nothing is published here yet, the feed does not resolve yet, and the hub cannot install from this
registry yet.** `extensions.remaestro.app` is settled as the address but has no DNS record and no
Pages custom domain behind it — written down first so the hub compiles in a constant that will not
have to move, since that URL is the one part of this that cannot change without reaching every hub in
the field. The hub-side
half — finding a plugin, launching it, and the protocol version negotiation that `abi` refers to —
is being built, and the negotiation deliberately comes first: adding it after strangers exist is
itself the breaking change it prevents. The registry is being stood up ahead of that so its shape is
settled before anyone depends on it, rather than after.
