# The submission manifest

One file per plugin, at `plugins/<id>/plugin.json`, validated against
[`schema/submission.schema.json`](../schema/submission.schema.json). Unknown fields are **rejected
rather than ignored**: a field the registry does not understand is a claim it cannot check, and a
manifest that silently drops half of what it says is worse than one that fails.

There is a second `plugin.json` — the one **inside** each archive, which the hub reads to learn what
to run. They are different files with overlapping fields, and CI checks that they agree. See
[Inside the archive](#inside-the-archive).

```jsonc
{
  "id": "com.acme.lamp",
  "name": "Acme Lamp",
  "summary": "Turns Acme lamps on and off, and dims them.",
  "description": "Longer prose for the plugin's page. CommonMark.",
  "publisher": "com.acme",
  "kind": "driver",
  "license": "MIT",
  "homepage": "https://acme.example/lamp",
  "source": "https://github.com/acme/remaestro-lamp",
  "tags": ["lighting"],

  "versions": [
    {
      "version": "1.1.0",
      "abi": 1,
      "runtime": "native",
      "releasedAt": "2026-08-14",
      "sourceCommit": "9f1c0d3",
      "notes": "Dimming on the 2024 models.",
      "archives": {
        "linux-arm64": {
          "url": "https://github.com/acme/remaestro-lamp/releases/download/v1.1.0/lamp-1.1.0-linux-arm64.tar.gz",
          "sha256": "…64 hex…",
          "size": 16252928,
          "signature": "…base64…",
          "keyId": "2026-01"
        },
        "linux-x64": { "…": "…" }
      }
    }
  ]
}
```

## The fields that carry weight

**`id`** — reverse-DNS, lowercase, and it must equal the directory name. Allocated once and **never
reassigned**. This is the cheapest decision in the whole registry and the most expensive to reverse:
an entitlement, a pinned key, and an installed copy on somebody's hub all point at this string, so an
id that changes hands is a hub trusting different software under a name it already agreed to.

**`publisher`** — the id of a record in [`publishers/`](../publishers). A publisher is a record in
this repository rather than a string in your manifest, because everything that later attaches to a
publisher — a second plugin, a key rotation, a payee — has to attach to something. It cannot change
after the first publication.

**`license`** — an SPDX identifier from the list in
[`tools/registry/policy.py`](../tools/registry/policy.py). Required from your first submission even
though only free licences are accepted today, because adding a required field later would invalidate
every manifest already published.

**`source`** — checked that it resolves, and shown beside your plugin permanently. It is **never**
checked that the archives were built from it. Only building them ourselves would show that, and this
project does not have build infrastructure for two architectures even for its own releases.

**`versions`** — append-only. A published version is never edited and never deleted; it is
*withdrawn*. CI compares your pull request against the registry as it stood before, and refuses an
edit to bytes that hubs have already checked their copy against.

## Architectures

`archives` is keyed by runtime identifier, and there are two: **`linux-arm64`** and
**`linux-x64`**. That is what the hub ships as and what the appliance and the cloud are; anything
else is a developer's laptop, which is the SDK's local-run path rather than the registry's problem.

One archive per architecture. A box downloads its own and only its own — the appliance's data
partition is 3 GiB and does not grow.

Publishing only one architecture is fine. Publishing one and saying nothing about the other is not:

```jsonc
"archives": { "linux-arm64": { "…": "…" } },
"unsupportedRids": { "linux-x64": "no x64 build until we have a runner for it" }
```

The reason is not paperwork. Without it the hub cannot tell someone whether this plugin has no build
for their box or whether something failed, and those need different sentences.

## `abi`

**One integer per version: the `driver.proto` protocol version the build was made against.** It is
the same across every architecture — if two architectures disagree about it they are different
software, and CI refuses them.

It exists so a hub can refuse a plugin it cannot speak to *with a sentence*, before downloading
fifteen megabytes, rather than by failing at the first unknown call.

> **Two things to know before you rely on this.**
>
> **There is no abi 1 in the field yet.** The protocol version field is part of the version
> negotiation work that has to land in the hub before a single package is published — it is
> deliberately first in the plan, because *adding* negotiation after third parties exist is itself
> the breaking change that negotiation exists to prevent. Until it ships, `abi: 1` describes an
> intent rather than something a hub can check.
>
> **A single integer cannot say everything the hub-side design will eventually want to.** The
> negotiation design has the plugin declare two things to the hub: the protocol version it was built
> against, and the *oldest* hub protocol it can still work with. This manifest carries only the
> first. That is enough for the registry to refuse an obviously incompatible submission, and it is
> not enough to express "built against 3, works fine on 2".
>
> Rather than invent the second field before the hub has one, the registry states the reading that
> keeps adding it later safe: **a manifest with no declared floor is read as though its floor equals
> its `abi`.** So a future `minHubAbi` can only ever widen what an existing manifest claims, never
> narrow it, and every manifest published before it existed keeps meaning exactly what it meant.

## `runtime`

What the box must already have. `native` is a self-contained or static executable — one file per
architecture, no shared runtime. `python3` is present on the appliance and in the container.

There is no `node`: **Node is on neither box**, so a Node plugin ships as `native` (a
single-executable build) or does not run. Better to read that here than to discover it.

A .NET plugin **must** be self-contained, single-file and trimmed. Framework-dependent is not an
option: the appliance has no shared `dotnet`, so a framework-dependent build works under Docker and
fails on the appliance, which is the worst available shape of bug. For scale: 15.5 MB
self-contained/single-file/trimmed, 116 MB without those flags.

## Withdrawing a version

Add a `withdrawn` block to the version. Do not delete it.

```jsonc
{ "version": "1.0.3", "withdrawn": { "at": "2026-08-20", "reason": "Bricks the 2019 bridge firmware." },
  "…": "…" }
```

A withdrawn version stops being offered, and the console warns anyone who has it installed. It does
**not** uninstall anything, and it must not be able to: a channel that can remove software from
somebody's house on our say-so is a worse thing to build than the problem it solves.

## Inside the archive

The archive is a gzipped tar with a `plugin.json` at its root. That file is what the hub reads to
learn what to run, and CI checks it against the submission — `id`, `version` and `abi` must match,
and `rid` must match the architecture it was published under.

```jsonc
{
  "id": "com.acme.lamp",
  "version": "1.1.0",
  "abi": 1,
  "kind": "driver",
  "runtime": "native",
  "rid": "linux-arm64",
  "exec": ["./acme-lamp"]
}
```

`exec` is an argv relative to the package root, and it must be there and non-empty: without it there
is nothing to launch. Naming an interpreter here is what saves you smuggling one through a shebang —
which matters, because a shebang must carry an absolute interpreter path (so `#!/usr/bin/env python3`
cannot select a virtualenv).

**The process contract, which is the opinionated part:**

1. Serve `maestro.Driver` from `driver.proto` over gRPC h2c, on the address in the environment.
2. Answer `Describe` promptly — the hub retries for about ten seconds and then gives up.
3. Exit on `SIGTERM`. The hub owns your process and kills the tree on dispose.
4. Do not fork or daemonise. The hub reads your liveness from the process it started.
