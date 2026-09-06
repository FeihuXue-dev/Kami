#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-"$ROOT/dist/kami.zip"}"
case "$OUT" in
  /*) ;;
  *) OUT="$ROOT/$OUT" ;;
esac
PACKAGE_ROOT_NAME="${KAMI_PACKAGE_ROOT_NAME:-kami}"
PACKAGE_MAX_BYTES="${KAMI_PACKAGE_MAX_BYTES:-6000000}"
SKILL_DIR="skills/kami"
# Paths are relative to the skill directory. Anything that is not the skill
# (website, tests, commercial fonts, rendered examples) lives outside it, so
# this list only guards against regressions inside skills/kami.
PACKAGE_FORBIDDEN_RE='^(assets/examples/|assets/fonts/.*\.(ttf|otf)$|scripts/tests/|.*/__pycache__/|.*\.pyc$|.*\.DS_Store$)'
PACKAGE_REQUIRED_ENTRIES=(
  "SKILL.md"
  "CHEATSHEET.md"
  "VERSION"
  "LICENSE"
  "assets/images/logo.svg"
  "assets/fonts/JetBrainsMono.woff2"
  "assets/templates/resume.html"
  "assets/templates/landing-page.html"
  "assets/diagrams/sequence.html"
  "references/design.md"
  "scripts/build.py"
  "scripts/ensure-fonts.sh"
  "scripts/ensure_mathjax.sh"
  "scripts/math_render.py"
  "scripts/mathjax_svg.js"
  "scripts/mathjax-runtime/package.json"
  "scripts/mathjax-runtime/package-lock.json"
  "scripts/site_facts.py"
  "scripts/content.py"
  "scripts/html_visibility.py"
  "scripts/visual.py"
  "scripts/mcp_server.py"
  "references/schemas/resume.json"
)

mkdir -p "$(dirname "$OUT")"
if [ -d "$OUT" ]; then
  echo "ERROR: package output is a directory: $OUT" >&2
  exit 1
fi

cd "$ROOT"

MANIFEST="$(mktemp)"
FILTERED_MANIFEST="$(mktemp)"
ZIP_MANIFEST="$(mktemp)"
STAGING="$(mktemp -d)"
CANDIDATE_DIR="$(mktemp -d "$(dirname "$OUT")/.kami-package.XXXXXX")"
CANDIDATE="$CANDIDATE_DIR/kami.zip"
trap 'rm -f "$MANIFEST" "$FILTERED_MANIFEST" "$ZIP_MANIFEST"; rm -rf "$STAGING" "$CANDIDATE_DIR"' EXIT

git ls-files -- "$SKILL_DIR" | sed "s#^$SKILL_DIR/##" > "$MANIFEST"
awk '
  /(^|\/)__pycache__\// { next }
  /\.pyc$/ { next }
  /(^|\/)\.DS_Store$/ { next }
  /^assets\/examples\// { next }
  { print }
' "$MANIFEST" > "$FILTERED_MANIFEST"

if [ ! -s "$FILTERED_MANIFEST" ]; then
  echo "ERROR: no tracked files under $SKILL_DIR" >&2
  exit 1
fi

while IFS= read -r entry; do
  dest="$STAGING/$PACKAGE_ROOT_NAME/$entry"
  mkdir -p "$(dirname "$dest")"
  cp -p "$SKILL_DIR/$entry" "$dest"
done < "$FILTERED_MANIFEST"

(
  cd "$STAGING"
  find "$PACKAGE_ROOT_NAME" -type f | sort > "$ZIP_MANIFEST"
  zip -X -q "$CANDIDATE" -@ < "$ZIP_MANIFEST"
)

entries="$(zipinfo -1 "$CANDIDATE")"
bad_root="$(printf '%s\n' "$entries" | awk -v prefix="${PACKAGE_ROOT_NAME}/" 'index($0, prefix) != 1 { print }')"
if [ -n "$bad_root" ]; then
  echo "ERROR: package entries must live under ${PACKAGE_ROOT_NAME}/:" >&2
  printf '%s\n' "$bad_root" >&2
  exit 1
fi

stripped_entries="$(printf '%s\n' "$entries" | sed "s#^${PACKAGE_ROOT_NAME}/##")"
if forbidden_entries="$(printf '%s\n' "$stripped_entries" | grep -E "$PACKAGE_FORBIDDEN_RE")"; then
  echo "ERROR: disallowed package entry found in $OUT:" >&2
  printf '%s\n' "$forbidden_entries" >&2
  exit 1
fi

for required in "${PACKAGE_REQUIRED_ENTRIES[@]}"; do
  if ! printf '%s\n' "$entries" | grep -Fxq "${PACKAGE_ROOT_NAME}/${required}"; then
    echo "ERROR: required package entry missing from $OUT: ${PACKAGE_ROOT_NAME}/${required}" >&2
    exit 1
  fi
done

size_bytes="$(wc -c < "$CANDIDATE" | tr -d '[:space:]')"
if (( size_bytes > PACKAGE_MAX_BYTES )); then
  echo "ERROR: package exceeds ${PACKAGE_MAX_BYTES} bytes: ${size_bytes} bytes" >&2
  exit 1
fi

mv -f "$CANDIDATE" "$OUT"
echo "OK: package audit passed (${size_bytes} bytes, limit ${PACKAGE_MAX_BYTES})"
echo "OK: wrote $OUT"
