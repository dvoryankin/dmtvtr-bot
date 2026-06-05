#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="${BOT_DIR:-/root/bots}"
ENV_FILE="${ENV_FILE:-${BOT_DIR}/.env}"
CHAT_ID="${FRIDAY_GIF_CHAT_ID:--1003681962162}"
ANIMATION="${FRIDAY_GIF_ANIMATION:-CgACAgQAAyEFAATbdkiyAAEBGz5p1O3CJ1whmIVMGFQ4S4Ob02VcSAACcAoAAhZm5VGmyo-WwUXBSzsE}"
CAPTION="${FRIDAY_GIF_CAPTION:-френдзы и нейборсы}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "env file not found: $ENV_FILE" >&2
    exit 1
fi

BOT_TOKEN="$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | head -n 1 | cut -d= -f2-)"
if [[ -z "$BOT_TOKEN" ]]; then
    echo "BOT_TOKEN is empty in $ENV_FILE" >&2
    exit 1
fi

response="$(
    curl -fsS "https://api.telegram.org/bot${BOT_TOKEN}/sendAnimation" \
        -d "chat_id=${CHAT_ID}" \
        -d "animation=${ANIMATION}" \
        -d "caption=${CAPTION}"
)"

echo "$response"
