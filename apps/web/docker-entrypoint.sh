#!/bin/sh
# Point the /v1 rewrite at the runtime API origin. Next 16 bakes rewrites at build time, so the image is
# built with a placeholder origin and this swaps it in (idempotent; a no-op when the origin is unchanged).
set -eu
PLACEHOLDER="http://shilpa-api-origin.placeholder.invalid:8000"
ORIGIN="${SHILPA_API_ORIGIN:-}"
if [ -n "$ORIGIN" ]; then
  ORIGIN="${ORIGIN%/}"
  case "$ORIGIN" in
    http://*|https://*) ;;
    *) echo "SHILPA_API_ORIGIN must start with http:// or https:// (got: $ORIGIN)" >&2; exit 64 ;;
  esac
  # Last-used origin is remembered so a restart with a different value still works.
  CURRENT="$PLACEHOLDER"
  [ -f .next/.api-origin ] && CURRENT="$(cat .next/.api-origin)"
  if [ "$CURRENT" != "$ORIGIN" ]; then
    grep -rlF "$CURRENT" server.js .next --include=*.json --include=*.js 2>/dev/null | while read -r f; do
      sed -i "s|$CURRENT|$ORIGIN|g" "$f"
    done
    printf '%s' "$ORIGIN" > .next/.api-origin
  fi
fi
exec "$@"
