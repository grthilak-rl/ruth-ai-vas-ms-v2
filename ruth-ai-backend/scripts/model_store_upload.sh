#!/usr/bin/env bash
# Upload .pt files into a Model Management draft over the chunked API,
# using the same protocol as the web UI, and check the server's sha256
# against the local file.
#
#   TOKEN=<admin token> scripts/model_store_upload.sh <base_url> <model_pk> file.pt [...]
#
# base_url: e.g. http://localhost (through nginx, as the browser does).
# The local sha256 is sent at init, so the server refuses a corrupted file;
# an interrupted run resumes: chunks the server already has are skipped.
# Needs bash, curl (>= 7.76), GNU dd, sha256sum, python3.
set -euo pipefail

if [ $# -lt 3 ]; then
    echo "usage: TOKEN=... $0 <base_url> <model_pk> file.pt [file.pt ...]" >&2
    exit 64
fi
: "${TOKEN:?set TOKEN to an admin token}"

API="${1%/}/api/v1/admin/model-store"
MODEL="$2"
shift 2

CURL=(curl -sS --fail-with-body -H "Authorization: Bearer $TOKEN")
field() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

STATUS=0
for path in "$@"; do
    name="$(basename "$path")"
    size="$(stat -c %s "$path")"
    local_sha="$(sha256sum "$path" | cut -d' ' -f1)"

    init="$("${CURL[@]}" -H 'Content-Type: application/json' \
        -d "{\"filename\": \"$name\", \"size_bytes\": $size, \"sha256\": \"$local_sha\"}" \
        "$API/models/$MODEL/uploads")"
    upload_id="$(field "['id']" <<<"$init")"
    chunk_size="$(field "['chunk_size']" <<<"$init")"
    total="$(field "['total_chunks']" <<<"$init")"
    have=" $(field "['received_chunks']" <<<"$init" | tr -d '[],') "

    sent=0
    for ((i = 0; i < total; i++)); do
        if [[ "$have" == *" $i "* ]]; then continue; fi
        dd if="$path" bs="$chunk_size" skip="$i" count=1 iflag=fullblock status=none |
            "${CURL[@]}" -X PUT -H 'Content-Type: application/octet-stream' \
                --data-binary @- "$API/uploads/$upload_id/chunks/$i" >/dev/null
        sent=$((sent + 1))
    done

    done_json="$("${CURL[@]}" -X POST "$API/uploads/$upload_id/complete")"
    server_sha="$(field "['file']['sha256']" <<<"$done_json")"
    if [ "$server_sha" = "$local_sha" ]; then
        printf 'OK        %-24s %10s bytes  %s  (%d/%d chunks sent)\n' "$name" "$size" "$server_sha" "$sent" "$total"
    else
        printf 'MISMATCH  %-24s local %s server %s\n' "$name" "$local_sha" "$server_sha"
        STATUS=1
    fi
done
exit "$STATUS"
