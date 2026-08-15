# publishers/

One `<publisher-id>.json` per publisher, holding the name shown beside their plugins and the public
keys their archives are signed with.

A publisher is a record here rather than a string in a manifest, because everything that later
attaches to a publisher — a second plugin, a key rotation, a payee — has to attach to something.

**The keys in these files are append-only.** They are pinned on a publisher's first publication and
every later archive must be signed by one of them; a key is retired by setting its `status` to
`revoked`, never by deleting it. Adding one is a reviewed operation, because an account takeover and
a legitimate rotation are the same diff. See [docs/signing.md](../docs/signing.md).

These are public keys. Nothing secret belongs in this directory or anywhere else in this repository.
