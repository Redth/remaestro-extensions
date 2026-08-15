# keys/

The **public** half of the index signing key, one file per generation, as base64 SPKI on a single
line:

```
keys/index-1.pub
```

It is published here so anyone can verify the feed without asking us, and so the signing step in CI
can check that it signed with the key hubs actually carry. That check is not ceremony: a signature
made with the wrong generation verifies perfectly against itself and fails on every box in the field.

**There is no private key in this repository, and there never will be.** The private half lives in
the secret store and in this repository's Actions secret, is read at the moment of use, and is handed
to `openssl` through a file descriptor rather than written to the workspace.
`tools/sign-index.sh` has no fallback that reads a key from a file, on purpose.

`index-1.pub` is not here yet — the key has not been provisioned. Until it is,
`.github/workflows/publish-index.yml` will fail at its verify step, which is the correct failure:
publishing an unverifiable feed would be worse than publishing none.

To add a generation: put its public half here, ship a hub release that trusts it alongside the
current one, wait for the field to move, then drop the old file. Rotation is possible precisely
because this key signs no hub, no OS image and no driver — that is the argument that made a signing
key in CI acceptable here at all. See [docs/signing.md](../docs/signing.md).
