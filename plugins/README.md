# plugins/

One directory per plugin, named exactly for its id, holding `plugin.json` — and optionally a
`README.md` and an `icon.png`. Nothing else: artifacts live in the publisher's own storage, and the
registry carries a URL and a digest rather than bytes.

Empty for now. See [CONTRIBUTING.md](../CONTRIBUTING.md) to add the first one, and
[docs/manifest.md](../docs/manifest.md) for what every field commits you to.
