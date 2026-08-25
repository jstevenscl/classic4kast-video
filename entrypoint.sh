#!/bin/sh
# Auto-generates and persists AGENT_TOKEN when the operator hasn't set one --
# now that all three services share one container, the token only ever
# crosses localhost between supervised processes, so there's no real reason
# to force every user to invent and pass in a random secret by hand (the old
# 3-container compose's AGENT_TOKEN:? requirement). Persisted to the data
# volume so it survives container restarts/recreates, not just regenerated
# (and therefore invalidating itself) every boot.
set -e

mkdir -p /data/renderer /data/web /data/webchannel

if [ -z "$AGENT_TOKEN" ]; then
  TOKEN_FILE=/data/.agent_token
  if [ -f "$TOKEN_FILE" ]; then
    AGENT_TOKEN=$(cat "$TOKEN_FILE")
  else
    AGENT_TOKEN=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    echo "$AGENT_TOKEN" > "$TOKEN_FILE"
  fi
  export AGENT_TOKEN
fi

# Every supervised program inherits this shell's exported environment
# (supervisord itself, then its children) -- only AGENT_TOKEN needs runtime
# resolution; every other setting is a static default in supervisord.conf.
exec supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
