"""Reading the registry as it stood before this pull request.

Most of what makes this registry trustworthy is not a property of a submission — it is a
property of the *difference* between a submission and what was already published. A key that
is pinned, an id that is never reassigned, a version that is never edited after the fact: none
of those can be checked by looking at one file.

So the base ref is read out of git rather than out of a database. That also means the registry's
own history is the transparency log — every (plugin, version, digest, key) that was ever offered
is in it, and a targeted bad artifact served to one hub stays detectable afterwards. That is a
property of the design rather than a feature anyone built.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class GitError(Exception):
    pass


def ref_exists(repo: str, ref: str) -> bool:
    result = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def read_json_at(repo: str, ref: str, path: str) -> Any | None:
    """The file as of `ref`, or None if it was not there. Malformed JSON at the base ref is
    treated as absent: the base is history, and refusing to validate today's PR because of
    yesterday's typo helps nobody."""

    result = subprocess.run(
        ["git", "-C", repo, "show", f"{ref}:{path}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def paths_at(repo: str, ref: str, prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", repo, "ls-tree", "-r", "--name-only", ref, "--", prefix],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]
