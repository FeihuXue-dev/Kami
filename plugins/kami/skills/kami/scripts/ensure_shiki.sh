#!/usr/bin/env bash
# Ensure Shiki's build-time syntax highlighter is available in a user cache.
set -euo pipefail

if [ "$(uname -s)" = "Darwin" ]; then
  CACHE_HOME="$HOME/.cache"
else
  CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
fi
SHIKI_ROOT="${KAMI_SHIKI_ROOT:-$CACHE_HOME/kami/shiki}"

if node - "$SHIKI_ROOT" <<'NODE' >/dev/null 2>&1
const root = process.argv[2];
try {
  require.resolve("shiki/package.json", { paths: [root] });
  process.exit(0);
} catch (_) {
  process.exit(1);
}
NODE
then
  echo "OK: Shiki available at $SHIKI_ROOT"
  exit 0
fi

echo "Installing Shiki for build-time syntax highlighting at $SHIKI_ROOT"
npm install --no-save --prefix "$SHIKI_ROOT" shiki@4.4.3
printf 'OK: Shiki installed at %s\n' "$SHIKI_ROOT"
