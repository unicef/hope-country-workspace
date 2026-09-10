#!/bin/bash
set -e

# Built as argv array so paths with '=' are not mangled by Circus env substitution.
args=(
  uwsgi
  --http :8000
  -H /venv
  --module country_workspace.config.wsgi
  --mimefile=/conf/mime.types
  --uid hope
  --gid unicef
  --buffer-size 8192
  --http-buffer-size 8192
)

static_url="${STATIC_URL:-/static/}"
static_root="${STATIC_ROOT:-}"

if [ -n "${static_root}" ] && [ -d "${static_root}" ]; then
  echo "uwsgi static-map: ${static_url}=${static_root}"
  args+=(--static-map "${static_url}=${static_root}")
else
  echo "uwsgi: skipping static-map (STATIC_ROOT='${static_root}' missing or not a directory)"
fi

exec "${args[@]}"
