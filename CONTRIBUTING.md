# Submitting a plugin

Everything happens in a pull request. There is no service to sign up for, no token to hold, and no
account beyond the GitHub one you are already reading this with.

Before you start, read the top of [the README](README.md). It says plainly what installing a plugin
means for the person who installs yours, and the rest of this page assumes you have.

---

## Once: become a publisher

**Pick a publisher id.** Reverse-DNS, lowercase, something you control — `com.acme`,
`io.github.yourname`. It is allocated once and never reassigned, and every plugin you publish hangs
off it.

**Make a signing key.** Full commands in [docs/signing.md](docs/signing.md):

```sh
openssl ecparam -name prime256v1 -genkey -noout -out remaestro-publisher.pem
chmod 600 remaestro-publisher.pem
openssl ec -in remaestro-publisher.pem -pubout -outform DER | base64   # the public half
```

Keep the private half. It is pinned on your first publication, and **every later version of every
plugin you publish must be signed by it**. Losing it means you cannot publish an update — see
[rotation](docs/signing.md#rotation), which is a reviewed operation rather than a form.

**Add `publishers/<your-id>.json`:**

```json
{
  "id": "com.acme",
  "name": "Acme Ltd",
  "contact": "https://github.com/acme",
  "keys": [
    {
      "id": "2026-01",
      "algorithm": "ecdsa-p256-sha256",
      "publicKey": "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE…",
      "addedAt": "2026-01-04",
      "status": "active"
    }
  ]
}
```

`name` and `contact` are shown beside every one of your plugins, permanently. They are a claim rather
than an identity check unless you get verified, and the console says which.

**Optional: get verified.** Publish a document at the URL your publisher id implies —
`com.acme` means `https://acme.com/.well-known/remaestro-publisher.txt`, `io.github.acme` means
`https://acme.github.io/...` — containing the line `remaestro-publisher=com.acme`, and say so in your
pull request. A maintainer reads it, and if it holds up they add a record in `verification/`. You
cannot write that record yourself and there is no field in this file for it: a tier its own subject
writes is a tier nobody checked.

**Verified means we checked who a publisher is. It never means a plugin is safe.** It is an identity
signal and nothing more — your plugin still runs with the hub's own privileges either way, and being
unverified is the ordinary state rather than a mark against you.

If you are on GitHub Pages, commit an empty `.nojekyll` at the root of the repository Pages builds
from, or Jekyll will drop `.well-known/` from your site and the file will be in your repository and
not on the web. Full detail, including what CI checks and what a person decides:
[docs/verification.md](docs/verification.md).

---

## Each release: build, sign, submit

**1. Build one archive per architecture.** A gzipped tar with a `plugin.json` at its root and your
entrypoint beside it. Two architectures matter: `linux-arm64` and `linux-x64`. Publishing only one is
fine as long as you say so in `unsupportedRids`.

If you are building .NET: self-contained, single-file and trimmed, or it will not run on the
appliance. If you are building Python: vendor your dependencies — `grpcio`'s native extension is
architecture *and* Python-minor specific, so an archive is per (architecture × Python version). If
you are thinking of Node: there is no Node on the box, so it has to be a single-executable build
declared as `native`.

**2. Put the archives somewhere anonymously downloadable, and permanent.** GitHub Release assets on
your own repository are the natural home. The registry carries an absolute URL and a digest, so where
the bytes live is your choice and their integrity is not.

Once a version is published here, **the bytes at that URL must never change.** Publish a new version
instead; CI refuses a repointed one.

**3. Sign each archive** with your publisher key, over the archive bytes:

```sh
openssl dgst -sha256 -sign remaestro-publisher.pem -out lamp.sig.der lamp-1.1.0-linux-arm64.tar.gz
base64 < lamp.sig.der
```

**4. Add or update `plugins/<id>/plugin.json`.** Every field is documented in
[docs/manifest.md](docs/manifest.md). Append the new version; never edit or delete an old one.

**5. Check it yourself before opening the pull request.** This runs the same checks CI does:

```sh
pip install -r tools/requirements.txt
PYTHONPATH=tools python -m registry.validate --repo . --base-ref origin/main
```

`--offline` skips everything that leaves your machine, for a quick schema pass. It also skips the
digest and signature checks, which are most of the value, so it is a first pass and not the check.

**6. Open the pull request.** One plugin per pull request. Say in the description what changed and
why anyone would want it.

---

## What happens then

**CI runs first, and it decides everything a machine can decide** — schema, ids, URLs, digests,
signatures against your pinned key, and whether anything already published has moved. It reports
each failure with the rule it broke. If CI is red, a reviewer will usually wait for you rather than
read it, so there is no need to ask.

**Then a person reads it.** The manifest, the description, the source repository if there is one, and
the diff. What they are judging is intent and fit: whether this is a real plugin someone wants,
whether the description matches what it appears to do, whether the id and name are honest about who
you are. Fifteen minutes for a new plugin, a glance for a version bump signed by a key we already
have.

**On merge, CI regenerates the index and signs it**, and your plugin is installable. Nobody signs
your binary — see below.

---

## What we vouch for, and what we do not

We check that the bytes at your URL hash to what your manifest says, and that they were signed by the
key you have been pinned to since your first publication. That is what a reviewer's approval means,
and it is all it means.

**We do not vouch for what your plugin does.** We do not audit it, we do not run it against a
household, we do not check the binary against the source you linked, and we never sign your archive.
A signature from this project over your binary would read as a warranty to the person installing it,
and there is no warranty to give: your plugin runs with the hub's own privileges on their box.

If your description implies otherwise — "certified", "safe", "sandboxed", "audited" — you will be
asked to change it before merge. That is not pedantry about wording. Somebody reads that sentence
and then decides whether to run your code as root on the machine that holds their house keys.

**That includes the tier.** The registry may say you are `verified`, and it means one thing: somebody
here checked you control the name your id claims. Writing "verified" in your own summary or
description, in any sense beyond that, is the same claim under a different heading and is refused for
the same reason.

By submitting you are also confirming you have the right to distribute what you are publishing, under
the licence you declared.

## What submitting grants us

Your plugin stays yours, under whatever licence you declared. This is only about the manifest.

By opening a pull request you grant this project the right to publish and redistribute the manifest
you submitted, including as part of the generated index — a document built out of everyone's
submissions, served under our signature. That last part is the reason this paragraph exists: we make
a derived document from what you wrote and sign it, and nobody should have to work out for themselves
that they agreed to that. The registry's own files are [MIT](LICENSE), and your manifest becomes one
of them.

---

## Things that will be refused

- **A signature that does not verify against your pinned key.** This is the check the registry exists
  for, and there is no override.
- **Editing, deleting or repointing a version that has already been published.** Hubs have already
  checked their copy against those digests. Publish a new version.
- **Claiming an id that is not yours**, or one that has been used before. Ids are never reassigned.
- **A new key on an existing publisher without approval.** An account takeover and a legitimate
  rotation are the same diff; a maintainer has to say which this is, and may ask you to confirm out
  of band.
- **Committing an artifact into this repository.** The registry carries URLs and digests; it never
  carries bytes.
- **A tier written into your own submission.** There is no field for it in either document you
  submit, so it arrives as an unknown field and is refused. A verification is a maintainer's record
  of something they checked, in a directory you cannot write to.
- **Copy that implies review means safety.**

## Withdrawing something

Open a pull request adding a `withdrawn` block to the version, with a date and a real reason. It
stops being offered and the console warns anyone who has it installed. It does not uninstall
anything, from anyone — nothing here can, and nothing here should be able to.

If you have found a serious problem in somebody else's published plugin, open an issue, or reach a
maintainer privately if saying it in public would put people at risk first.
