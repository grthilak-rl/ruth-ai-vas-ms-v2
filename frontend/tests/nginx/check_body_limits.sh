#!/usr/bin/env bash
# Body-size limits of nginx.conf.template, tested against real nginx.
#
# Boots the template in nginx:alpine (as the frontend image does) with a stub
# upstream named ruth-ai-vas-backend that answers 200 to anything, then sends
# bodies of various sizes. Asserts:
#   - every /api/ route except the chunk PUT keeps nginx's default 1 MB limit
#   - only /api/v1/admin/model-store/uploads/<uuid>/chunks/<n> accepts up to 17 MB
#
# Usage: tests/nginx/check_body_limits.sh [path/to/nginx.conf.template]
# Needs docker and curl; leaves nothing running.
set -euo pipefail

TEMPLATE="$(realpath "${1:-$(dirname "$0")/../../nginx.conf.template}")"
NET="nginx-limits-$$"
STUB="nginx-limits-stub-$$"
SUT="nginx-limits-sut-$$"
WORK="$(mktemp -d)"
trap 'docker rm -f "$SUT" "$STUB" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; rm -rf "$WORK"' EXIT

cat > "$WORK/stub.conf" <<'EOF'
server {
    listen 8080;
    client_max_body_size 0;
    location / { return 200 "stub-ok\n"; }
}
EOF

docker network create "$NET" >/dev/null
docker run -d --name "$STUB" --network "$NET" --network-alias ruth-ai-vas-backend \
    -v "$WORK/stub.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine >/dev/null
docker run -d --name "$SUT" --network "$NET" -p 127.0.0.1::80 \
    -e VAS_PROXY_URL=http://ruth-ai-vas-backend:8080 \
    -v "$TEMPLATE:/etc/nginx/templates/default.conf.template:ro" nginx:alpine >/dev/null

PORT="$(docker port "$SUT" 80/tcp 2>/dev/null | head -1 | sed 's/.*://' || true)"
READY=0
for _ in $(seq 1 30); do
    if curl -fs "http://127.0.0.1:$PORT/nginx-health" >/dev/null 2>&1; then READY=1; break; fi
    sleep 0.5
done
if [ "$READY" != 1 ]; then
    echo "FAIL  nginx did not start with this template:"
    docker logs "$SUT" 2>&1 | tail -5
    exit 2
fi

UUID="0b6f3c8e-1d2a-4c5b-9e7f-123456789abc"
mkbody() { head -c "$1" /dev/zero > "$WORK/body-$1"; echo "$WORK/body-$1"; }
KB900=$(mkbody $((900 * 1024)))
MB2=$(mkbody $((2 * 1024 * 1024)))
MIB16=$(mkbody $((16 * 1024 * 1024)))
MB18=$(mkbody $((18 * 1024 * 1024)))

FAILED=0
check() {  # check <expected> <method> <path> <bodyfile>
    local got
    got=$(curl -s -o /dev/null -w '%{http_code}' -X "$2" --data-binary "@$4" \
        -H 'Content-Type: application/octet-stream' "http://127.0.0.1:$PORT$3")
    if [ "$got" = "$1" ]; then
        printf 'ok    %s %-4s %-62s %s\n' "$got" "$2" "$3" "$(basename "$4")"
    else
        printf 'FAIL  %s %-4s %-62s %s (expected %s)\n' "$got" "$2" "$3" "$(basename "$4")" "$1"
        FAILED=1
    fi
}

echo "template: $TEMPLATE"
echo "--- existing /api/ routes: default 1 MB limit"
check 200 POST /api/v1/devices "$KB900"
check 413 POST /api/v1/devices "$MB2"
check 413 PUT  /api/v1/settings/shift-schedule "$MB2"
check 413 POST /api/v1/ai/inference "$MB2"
echo "--- other model-store routes: still 1 MB"
check 413 POST /api/v1/admin/model-store/models "$MB2"
check 413 POST "/api/v1/admin/model-store/uploads/$UUID/complete" "$MB2"
check 413 PUT  "/api/v1/admin/model-store/uploads/$UUID/chunks/0/extra" "$MB2"
check 413 PUT  "/api/v1/admin/model-store/uploads/not-a-uuid/chunks/0" "$MB2"

if grep -q 'model-store/uploads' "$TEMPLATE"; then
    echo "--- chunk PUT path: up to 17 MB"
    check 200 PUT "/api/v1/admin/model-store/uploads/$UUID/chunks/0" "$MIB16"
    check 200 PUT "/api/v1/admin/model-store/uploads/$UUID/chunks/127" "$MB2"
    check 413 PUT "/api/v1/admin/model-store/uploads/$UUID/chunks/0" "$MB18"
fi

exit "$FAILED"
