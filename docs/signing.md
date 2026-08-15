# Signing

Two keys, doing two different jobs, and the difference between them is the whole trust design.

| | Held by | Signs | What it proves |
|---|---|---|---|
| **Publisher key** | you, the publisher | your archives | that this update came from whoever published version one |
| **Index key** | this project, in CI | the generated index | that the list of names, versions, URLs and digests is the one we published |

**We never sign your plugin.** A signature from this project over a third party's binary is read as
a warranty — that is the social meaning of code signing — and under a model where a plugin runs with
the hub's own privileges there is no warranty to give. So the split above is not an accident of
tooling. It is the point.

## Your publisher key

ECDSA P-256, SHA-256, DER — the same shape the hub already verifies release manifests with.

**Make one.** It never leaves your keeping, and it never goes in a repository, a CI secret you share,
or this registry:

```sh
openssl ecparam -name prime256v1 -genkey -noout -out remaestro-publisher.pem
chmod 600 remaestro-publisher.pem
```

**The public half**, which is what you put in `publishers/<you>.json`:

```sh
openssl ec -in remaestro-publisher.pem -pubout -outform DER | base64
```

**Sign each archive** — the archive bytes themselves, not the digest, not the manifest:

```sh
openssl dgst -sha256 -sign remaestro-publisher.pem -out lamp.sig.der lamp-1.1.0-linux-arm64.tar.gz
base64 < lamp.sig.der          # this goes in the manifest as "signature"
```

**Check it before you open the pull request.** CI will do exactly this, and finding out here costs
you a minute rather than a review round trip:

```sh
openssl ec -in remaestro-publisher.pem -pubout -out pub.pem
openssl dgst -sha256 -verify pub.pem -signature lamp.sig.der lamp-1.1.0-linux-arm64.tar.gz
```

### Pinning, and what it is actually worth

Your key is **pinned on your first publication**. Every later version of every plugin you publish
must be signed by a key already in your publisher record, or CI refuses the submission.

What that buys, exactly: **a plugin's updates come from whoever published its first version.** It is
a narrow guarantee, and it is the most valuable one available here, because the realistic attack on a
marketplace is not a forged listing — it is a popular plugin's account being taken over and pushing a
malicious update to everyone who already trusted it.

What it does not buy: anything at all about the first install. That decision is the user's, made on
the publisher name, the source link, and the sentence at the top of the [README](../README.md).

### Rotation

Add a new key entry; never edit or delete an old one. Retire the old one by setting its `status` to
`revoked`, which keeps the history readable — a hub that meets an archive signed by a revoked key
should be able to say which key it was.

A rotation needs a maintainer's `key-rotation` label before CI will accept it, and that is
deliberate: **an account takeover and a legitimate new key are the same diff.** The label is a person
asserting they know which one this is. Expect to be asked, out of band, to confirm it is you.

Lost your key with no rotation possible? Then you cannot publish an update to that plugin, and the
answer is a new plugin id under the same publisher. That is unpleasant and it is the correct
behaviour: the alternative is a registry where losing a key and stealing an account look the same.

## The index key

Held by this project, used only by
[`.github/workflows/publish-index.yml`](../.github/workflows/publish-index.yml).

The standing rule for this project is that **no signing key lives in CI, for any channel** — the
keys that sign a hub, an OS image or a driver are used by a person, on their own machine, twelve or
so times a year. The index key is an explicit, argued exception, and the argument is worth keeping
where it can be checked:

- It signs **no hub, no OS image and no driver that ships with the product**. It is a second trust
  anchor, and a strictly weaker one.
- It is **rotatable by an app release**, which the release keys are not — that distinction is exactly
  what the original rule turns on.
- A compromise reaches only boxes that chose to install a plugin from this registry, and even then it
  cannot change **who** published a plugin, because that is pinned per publisher and lives in a
  file whose history is public. It can change which of a publisher's versions is offered.
- The alternative is a person in the loop of every third party's release cadence, forever. Signing a
  release twelve times a year is fine; signing an index every time a stranger merges a version bump
  is not the same thing, and pretending otherwise means a registry whose responsiveness is one
  person's availability.

**How it is provisioned, and the rules around it.** There is nothing here to copy — no key material
is in this repository, in any script, or on any developer machine as a matter of routine.

- The private key exists in exactly two places: the secret store, and this repository's Actions
  secret `REGISTRY_INDEX_KEY_PEM`. It is never written to a workspace, never echoed, and never
  exported into an environment that outlives the signing step. `tools/sign-index.sh` hands it to
  `openssl` through a file descriptor and **has no fallback that reads a key from a file**, on
  purpose: a fallback is how a key ends up in a checkout.
- The **public** half is committed at `keys/index-<generation>.pub` as base64 SPKI, so anyone can
  verify the feed without asking us, and so the signing step can check that it signed with the key
  hubs actually carry. That check is not ceremony — a signature made with the wrong generation
  verifies perfectly against itself and fails on every box in the field.
- Rotating it means: publish the new public half, ship a hub release that trusts both generations,
  wait for the field to move, then drop the old one. A hub that trusts no key for a feed treats that
  feed as untrusted and says so, rather than accepting anything.

## Verifying the feed yourself

Once the feed is live — the domain below is settled but not yet provisioned, see
[index-format.md](index-format.md#the-feed-base):

```sh
curl -sO https://extensions.remaestro.app/plugins/com.acme.lamp.json
curl -sO https://extensions.remaestro.app/plugins/com.acme.lamp.json.sig

{ echo "-----BEGIN PUBLIC KEY-----"; fold -w64 keys/index-1.pub; echo; echo "-----END PUBLIC KEY-----"; } > index.pem
base64 -d < com.acme.lamp.json.sig > sig.der
openssl dgst -sha256 -verify index.pem -signature sig.der com.acme.lamp.json
```

## The transparency log nobody had to build

Every `(plugin, version, digest, publisher key)` this registry has ever offered is in **this
repository's own git history**, publicly, with the pull request that introduced it. That means a bad
artifact served to one hub stays detectable afterwards. It is a property of keeping the registry in
git rather than a feature anyone wrote, and it is worth stating as one.
