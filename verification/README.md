# verification/

One `<publisher-id>.json` per **verified** publisher, recording that somebody here checked they
control the name their id claims, and what was checked.

**These are written by maintainers, never by the publisher a record is about.** That is the whole
reason this is a directory rather than a field in `publishers/<id>.json` — that file is submitted by
its own subject, so a tier in it would be self-asserted by construction. Neither the publisher record
nor a plugin manifest has a tier field, and both refuse an unknown one rather than ignoring it.

A pull request that adds or changes anything here needs the `verification` label, which only a
maintainer can apply, and [CODEOWNERS](../.github/CODEOWNERS) puts a maintainer's review on the path
as well.

Empty for now: nobody is verified, and `unverified` is the ordinary state rather than a mark against
anyone.

```json
{
  "publisher": "com.acme",
  "tier": "verified",
  "method": "well-known",
  "evidence": "https://acme.com/.well-known/remaestro-publisher.txt",
  "checkedAt": "2026-08-18",
  "checkedBy": "https://github.com/Redth",
  "status": "active",
  "note": "read the document by hand; the domain matches the id and the site is Acme's own"
}
```

`evidence` is checked against the URL the publisher id implies and refused if it is anything else —
the location is derived, never supplied. `status` goes to `withdrawn` with a date and a reason when a
verification stops being true; records are never deleted.

Every field, what counts as evidence, and the split between what CI enforces and what a person has to
decide: [docs/verification.md](../docs/verification.md).
