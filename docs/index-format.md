# The index — what a hub fetches

This is the wire shape, written down here because the hub-side fetcher does not exist yet and a
format nobody has specified is a format two people will implement differently. Nothing in the hub
reads any of this today.

Everything under `index/` is **generated** from the submissions by
[`tools/registry/build_index.py`](../tools/registry/build_index.py) and signed by CI. Do not edit it
by hand and do not commit it: it is published to the feed, not to the repository.

## The feed base

```
https://extensions.remaestro.app
```

**This is the constant a hub bakes in, and it is the part that cannot change**, because changing it
means an update every installed hub has to receive before it can find the registry again. The hosting
behind it can change freely — Pages today, a bucket or our own box later — and that is a DNS edit
rather than a release. Which is the whole reason it is a domain of ours and not the
`redth.github.io/remaestro-extensions` path Pages hands out.

> **The DNS record does not exist yet, and the Pages custom domain is not configured.** Nothing
> resolves at that name today. It is written down first so the hub-side fetcher has a settled
> constant to compile in rather than a placeholder to guess at, and so the two are never out of step.

## Two documents, and the split is not tidiness

```
https://extensions.remaestro.app/plugins/<id>.json        the install path — small, bounded, signed
https://extensions.remaestro.app/plugins/<id>.json.sig
https://extensions.remaestro.app/catalog.json             browse and search only — allowed to grow
https://extensions.remaestro.app/catalog.json.sig
```

**`plugins/<id>.json` is what a hub fetches to install or update.** It carries the newest offered
version *for each abi* and nothing else. The hub's release manifest refuses to be a growing list on
purpose — *"a document that grows with every release is a document that eventually fails to parse on
the oldest box in the field — the one that most needs to be able to update"* — and a marketplace
index is exactly the growing list that warning is about. Keying by abi rather than truncating to a
single "latest" keeps a hub that speaks an older protocol able to find something it can run.

**`catalog.json` is browse and search.** It may grow without limit, because the console is the only
thing that reads it and **no install or update path may depend on it**. That is the constraint that
keeps the other document small; if a hub ever needs the catalogue to install something, the split has
been undone.

## The per-plugin document

Schema: [`schema/index-plugin.schema.json`](../schema/index-plugin.schema.json).

```jsonc
{
  "schema": 1,
  "id": "com.acme.lamp",
  "name": "Acme Lamp",
  "summary": "…",
  "license": "MIT",
  "source": "https://github.com/acme/remaestro-lamp",
  "kind": "driver",

  "publisher": {
    "id": "com.acme",
    "name": "Acme Ltd",
    "contact": "https://github.com/acme",

    // Who they are, and never whether their plugin is safe. Always written, so a hub never infers it.
    "tier": "verified",
    // Only for "verified", and never for "official", where nothing was fetched. What was checked,
    // where, and when — so a console can name the domain instead of drawing a tick.
    "verification": {
      "method": "well-known",
      "evidence": "https://acme.com/.well-known/remaestro-publisher.txt",
      "checkedAt": "2026-08-18"
    },

    "keys": [
      { "id": "2026-01", "algorithm": "ecdsa-p256-sha256", "publicKey": "…base64 SPKI…", "status": "active" }
    ]
  },

  // Keyed by abi, as a string. The lookup that matters is "what do you have that I can speak".
  "latest": {
    "1": {
      "version": "1.1.0",
      "abi": 1,
      "runtime": "native",
      "releasedAt": "2026-08-14",
      "archives": {
        "linux-arm64": { "url": "https://…", "sha256": "…", "size": 16252928, "signature": "…", "keyId": "2026-01" }
      }
    }
  },

  "withdrawn": [ { "version": "1.0.3", "at": "2026-08-20", "reason": "…" } ],
  "generatedAt": "2026-08-15T00:00:00+00:00"
}
```

Revoked keys stay in `publisher.keys`. A hub that meets an archive signed by a revoked key has to be
able to say *which* key, not merely that something is wrong.

`catalog.json`'s rows carry `publisher.tier` and **not** the `verification` block. That is the same
split as everything else here: the browse list needs enough to draw a label and to filter, and the
evidence somebody would read before acting on it belongs on the document that installs.
[docs/verification.md](verification.md) is where the tiers come from and what they are allowed to
mean. **A tier is not the signature and must never be rendered as though it were** — what is verified
about an archive is its digest and the publisher key it was signed with, and that check is about the
bytes rather than about a person.

## What a hub is expected to do with it

Written as expectations rather than as code, because the fetcher is a later piece of work and this is
the half of it that is a contract.

1. **Fetch the document as bytes and verify the signature against the bytes as received**, before
   parsing. Parsing first and re-serialising checks a signature over something other than what was
   published, which is not a signature check.
2. **Verify with the index key baked into the build.** A feed the build carries no key for is one it
   does not trust: no key must never be read as any key.
3. **Choose the entry under `latest` whose abi this build speaks.** No entry means *"this plugin has
   nothing for a hub like yours"*, which is a sentence, not an error.
4. **Take the archive for this box's own architecture, and only that one.** A missing architecture
   means *"no build for this hub"*.
5. **Refuse an oversized artifact before downloading it**, on the declared `size`.
6. **Verify the SHA-256 over the downloaded bytes, then the publisher signature over the same bytes,
   against a key in `publisher.keys` with the matching `keyId`.** Both, in that order, before
   anything is unpacked.
7. **Stage inside the data directory** — `<data>/plugins/.staging` — never in `/tmp`, which is a
   256 MiB tmpfs in RAM on the appliance. Unpack to `.partial`, then move.
8. **Re-verify on every start.** A digest checked once and then trusted forever is a file that
   quietly became something else.
9. **Treat every name in this document as ours rather than as safe.** It arrives inside a signed
   document, which says who wrote it and nothing about whether a plugin id makes a good directory
   name. Use your own file names, never the URL's last segment.
10. **A plugin that disappears from the index keeps running.** Say so; never delete it. The same rule
    as the shipped firmware being the floor.
11. **Do not build any of this on the GitHub REST API.** Unauthenticated API access is 60 requests an
    hour per IP, shared by every hub behind one household NAT. Static documents carry no such limit.

## Install-by-URL, which owes this document nothing

**A hub can install a plugin from a `plugin.json` URL with no registry involved at all**, and that
path is built first. The registry is discovery; it is never a dependency. This is what keeps the
promise that the hub never needs a service of ours to do anything.

What install-by-URL gives up is exactly what the registry adds: nobody has checked the digest against
a signed document, nobody has pinned the publisher's key, and nobody has looked at the submission. It
should say so at the point of install.

## The signature

Detached, one `.sig` beside each document, holding **base64 of a DER-encoded ECDSA P-256 signature
over SHA-256 of the document's exact bytes**. The same shape, the same encodings and the same
verification call the hub already uses for release manifests — deliberately, so there is one
implementation of "check a signature" on a path somebody watches rather than two.

We sign the index. **We never sign a plugin.** See [signing.md](signing.md).
