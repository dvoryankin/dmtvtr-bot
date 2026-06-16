#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="${BOT_DIR:-/root/bots}"
ENV_FILE="${ENV_FILE:-${BOT_DIR}/.env}"
CHAT_ID="${FRIDAY_BESP_CHAT_ID:--1003681962162}"
PHOTO_PATH="${FRIDAY_BESP_PHOTO_PATH:-${BOT_DIR}/media/besp.jpg}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "env file not found: $ENV_FILE" >&2
    exit 1
fi

if [[ ! -f "$PHOTO_PATH" ]]; then
    echo "photo not found: $PHOTO_PATH" >&2
    exit 1
fi

BOT_TOKEN="$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | head -n 1 | cut -d= -f2-)"
if [[ -z "$BOT_TOKEN" ]]; then
    echo "BOT_TOKEN is empty in $ENV_FILE" >&2
    exit 1
fi

curl -fsS "https://api.telegram.org/bot${BOT_TOKEN}/sendPhoto" \
    -F "chat_id=${CHAT_ID}" \
    -F "photo=@${PHOTO_PATH}"
