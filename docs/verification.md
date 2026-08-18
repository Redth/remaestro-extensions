# Publisher tiers — official, verified, unverified

**The evidence a publisher is verified against lives at a URL derived from their publisher id, and
never at one they supply.** That single property is the whole security argument on this page:
everything else here is mechanism, and a check that followed a link out of a submission would be a
check of whatever the submitter chose to serve.

**Verified means we checked who a publisher is. It never means a plugin is safe.**

That sentence is not a disclaimer bolted onto a badge. It is what the tier *is*. Installing a plugin
runs an arbitrary binary on your hub with the hub's own privileges — every database, every credential,
the whole network — and [the README](../README.md) says so where a submitter and a user both read it.
Provenance is the only control that exists here. Not the main one; the only one. A tier is provenance
about a **publisher**, and there is no amount of it that becomes a statement about code.

---

## The three tiers, and three different authorities

| | What it says | Who decides it |
|---|---|---|
| **official** | Published by us. | A tuple in our own source — `OFFICIAL_PUBLISHERS` in [`tools/registry/policy.py`](../tools/registry/policy.py). |
| **verified** | Somebody here checked that this publisher controls the name their id claims. | A maintainer, in `verification/<id>.json`, against evidence CI re-reads. |
| **unverified** | Nobody checked. The name beside the plugin is a claim they made. | Nothing. It is the default, and the only thing anything here fails *into*. |

Three tiers and three authorities is the point, because the failure this design is built against is a
tier somebody awards themselves.

**Nothing fails upward.** A missing record, a withdrawn one, a malformed one, evidence that has
stopped resolving, a tier string this hub does not recognise — every one of them reads as
`unverified`. There is no path through this code where being broken is better than being absent.

---

## Why the record is not a field in the documents you submit

`plugins/<id>/plugin.json` and `publishers/<id>.json` are both written by the publisher they describe.
A tier in either would be self-asserted by construction — you would be telling us you are verified,
and we would be publishing it.

So there is no such field, in either schema, and both use `additionalProperties: false`: a manifest
carrying `"tier": "verified"` is **refused as an unknown field** rather than ignored. That is a
structural refusal rather than a rule a reviewer has to remember, and
[the test suite](../tests/test_registry.py) sabotages both of them on every run to prove it still is.

The verification lives at **`verification/<publisher-id>.json`**, a directory only maintainers write
to. See [the directory's README](../verification/README.md) for the record's shape.

---

## What counts as evidence

One method today: **`well-known`**.

Reverse the labels of the publisher id into a hostname, and fetch:

```
https://<reversed-id>/.well-known/remaestro-publisher.txt
```

| Publisher id | Where the evidence must be |
|---|---|
| `com.acme` | `https://acme.com/.well-known/remaestro-publisher.txt` |
| `io.github.acme` | `https://acme.github.io/.well-known/remaestro-publisher.txt` |

The document must contain a line naming the publisher:

```
remaestro-publisher=com.acme
```

That is all of it. One rule covers a domain and a GitHub account — `acme.github.io` is GitHub Pages
for that owner, so publishing the file there means pushing to a repository only they can push to —
and it needs no second method and no GitHub API, whose 60-requests-an-hour ceiling is shared by every
runner on a cloud provider.

**The location is computed from the id and is never read out of the record.** The record carries the
URL so a person can read it, and CI refuses the record if it is not the URL the id implies.

### If you publish on GitHub Pages, you need `.nojekyll`

**A Pages site running Jekyll — the default — drops dot-directories from its output.** Your
`.well-known/remaestro-publisher.txt` will be in your repository, visible on github.com, and **not on
your site**. Measured on 2026-08-18: `docs.github.com/.well-known/security.txt` and the same path on
`pages.github.com` both answer 404, and a Pages site that does serve a dot-file serves it because
`.nojekyll` is committed beside it.

Commit an empty file called `.nojekyll` at the root of the repository Pages builds from. This is a
prerequisite on that path rather than a footnote: without it the check fails in a way that looks
exactly like never having tried, which is why the refusal names the cause.

### Why not a DNS TXT record

It would prove the same thing and arguably prove it better. It is not used because
[the suite](../tests/test_registry.py) serves every byte from loopback through an origin map, and a
DNS check could never be made to refuse anything in a test. **A rule nobody has watched refuse
something is not a rule** — that is the standard the rest of this registry is held to, and a
verification check is the last place to make an exception to it.

---

## What CI enforces, and what a person has to do

The split matters more than either half, because the part CI cannot do is the part a badge implies it
did.

**CI enforces, on every pull request that touches a verification, and on every one of them weekly:**

- the evidence resolves, and is a document rather than a page;
- it sits at the URL the publisher id implies, and nowhere else;
- it carries the line naming that publisher;
- the record is about the publisher it is named for, and that publisher has a record in `publishers/`;
- the tier is `verified` — `official` is not spellable here, so it cannot be bought with a domain;
- a change under `verification/` carries the maintainer-only `verification` label;
- a verification is withdrawn, never deleted.

**A person has to decide** that whoever controls that name is the entity the record's name suggests,
and that the name is not deliberately confusable with somebody else's. Controlling `acme.com` and
being Acme Ltd are different facts, and only the first one is checkable.

**CI proves control of a name. It cannot prove identity, and nothing pretends it does.**

---

## Keeping it true

The check is re-run rather than remembered.

- **A pull request re-reads only the verification it touches.** Untouched records are left alone, for
  the same reason an untouched archive is not re-downloaded: a submission should cost what it
  proposes.
- **The [weekly audit](../.github/workflows/audit.yml) re-reads all of them**, with `--recheck-all`.
  That is what notices a domain that lapsed, was re-registered, or stopped serving the file — none of
  which happens on a day anybody opened a pull request.
- **A verification that stops being true is withdrawn**, with a date and a reason, and the publisher
  drops back to `unverified`. The record stays: *"we checked this and then stopped believing it"* is
  worth being able to read afterwards.

The `verification` label and [CODEOWNERS](../.github/CODEOWNERS) are two guards on the same door and
neither replaces the other. The label is what the validator can see. CODEOWNERS plus branch
protection requiring a code owner's review is what the **repository** enforces, and that is a setting
rather than something this repository's code can check — said plainly here rather than implied,
because a guard nobody can see the state of is one people assume is on.

---

## What a hub is given

The tier is in both published documents, and it is **always written** — a hub never has to infer
`unverified` from a missing field.

`catalog.json`, per row, carries the tier and nothing else about it: enough to draw a label and to
filter a list.

`plugins/<id>.json` — the document a hub reads when somebody is about to install — carries what was
checked, where, and when:

```jsonc
"publisher": {
  "id": "com.acme",
  "name": "Acme Ltd",
  "contact": "https://github.com/acme",
  "tier": "verified",
  "verification": {
    "method": "well-known",
    "evidence": "https://acme.com/.well-known/remaestro-publisher.txt",
    "checkedAt": "2026-08-18"
  },
  "keys": [ /* … */ ]
}
```

A console can then say *"the registry checked control of acme.com on 18 August 2026"*, which is a fact
somebody can go and confirm for themselves. A tick is not.

There is no `verification` block for `official`, because nothing was fetched. We know who we are, and
pretending to have checked a URL for it would be theatre.

**A tier is not the signature and must never be drawn as though it were.** What is verified about an
*archive* is its digest and the publisher key it was signed with — pinned on first install, and a
mismatch refuses. That check is about these bytes. A tier is about a person, it is carried in the same
signed document as everything else, and neither one substitutes for the other.
