#!/usr/bin/env bash
# Sign the generated index, and then check the signature we just made.
#
# What this signs is the *index* — names, versions, URLs and SHA-256s. It never signs anyone's
# plugin. A signature from this project over a third party's binary would be read as a warranty,
# and under a model where a plugin runs with the hub's privileges there is no warranty to give.
# Publishers sign their own archives; see docs/signing.md.
#
# The private key is never written to disk. It arrives in the environment, is handed to openssl
# through a file descriptor, and is gone when the process exits. There is no fallback that reads
# it from a file, on purpose — a fallback is how a key ends up in a workspace.
#
#   REGISTRY_INDEX_KEY_PEM="$(...)" tools/sign-index.sh --dir index --verify-with keys/index-1.pub
#
# The verify step is not ceremony. It is the only thing standing between "the workflow reported
# success" and "the feed is signed with the key hubs actually trust" — a signature made with the
# wrong generation of the key verifies perfectly against itself and fails on every box.

set -euo pipefail

dir="index"
verify_with=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) dir="$2"; shift 2 ;;
    --verify-with) verify_with="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${REGISTRY_INDEX_KEY_PEM:-}" ]]; then
  echo "REGISTRY_INDEX_KEY_PEM is not set. The signing key is read at the moment of use and" >&2
  echo "nothing is stored on the runner; there is no file for this script to fall back to." >&2
  exit 2
fi

if [[ ! -d "$dir" ]]; then
  echo "no such directory: $dir — run tools/registry/build_index.py first" >&2
  exit 2
fi

# Not `mapfile`: it is bash 4, and macOS ships bash 3.2, which is where a contributor checking
# their own signing setup most often is.
documents=()
while IFS= read -r line; do
  documents+=("$line")
done < <(find "$dir" -type f -name '*.json' | sort)

if [[ ${#documents[@]} -eq 0 ]]; then
  echo "there is nothing to sign in $dir" >&2
  exit 2
fi

signed=0
for document in "${documents[@]}"; do
  # /dev/fd/63 or similar: a pipe, not a file. The key is never on the filesystem.
  openssl dgst -sha256 -sign <(printf '%s' "$REGISTRY_INDEX_KEY_PEM") \
    -out "$document.sig.der" "$document"
  openssl base64 -A -in "$document.sig.der" -out "$document.sig"
  rm -f "$document.sig.der"
  signed=$((signed + 1))
done

echo "signed $signed document(s) in $dir"

if [[ -n "$verify_with" ]]; then
  if [[ ! -f "$verify_with" ]]; then
    echo "no public key at $verify_with, so nothing was verified. Refusing to call this signed." >&2
    exit 1
  fi
  # The published key is base64 SPKI, the same shape the hub bakes in for release channels.
  pem="$(mktemp)"
  trap 'rm -f "$pem"' EXIT
  {
    echo "-----BEGIN PUBLIC KEY-----"
    tr -d '\n' < "$verify_with" | fold -w 64
    echo
    echo "-----END PUBLIC KEY-----"
  } > "$pem"

  for document in "${documents[@]}"; do
    der="$(mktemp)"
    openssl base64 -d -A -in "$document.sig" -out "$der"
    if ! openssl dgst -sha256 -verify "$pem" -signature "$der" "$document" > /dev/null; then
      rm -f "$der"
      echo "$document was signed with a key that is not the one in $verify_with." >&2
      echo "Every hub would refuse this feed. Nothing is published." >&2
      exit 1
    fi
    rm -f "$der"
  done
  echo "verified $signed signature(s) against $verify_with"
else
  echo "warning: no --verify-with given, so nothing checked that this is the key hubs trust" >&2
fi
