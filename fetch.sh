#!/bin/bash
# Usage: ./fetch.sh <sources.txt>...
# Each line: "<path relative to the list> <url>"; "git+<url>" clones a repo.
# Existing files are skipped, so it is safe to re-run.
set -u
UA='Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0'
failed=0

for list in "$@"; do
    base=$(dirname "$list")
    while read -r path url; do
        [[ -z ${path:-} || $path == \#* ]] && continue
        dest="$base/$path"
        [[ -e $dest ]] && continue
        mkdir -p "$(dirname "$dest")"
        if [[ $url == git+* ]]; then
            git clone --depth 1 "${url#git+}" "$dest" || { echo "FAIL $dest"; failed=1; }
            continue
        fi
        if ! curl -sfL -A "$UA" --retry 3 --max-time 3600 -o "$dest.part" "$url"; then
            echo "FAIL $dest $url"; rm -f "$dest.part"; failed=1; continue
        fi
        if head -c 512 "$dest.part" | grep -qiE '<!doctype html|<html'; then
            echo "FAIL (got HTML page) $dest $url"; rm -f "$dest.part"; failed=1; continue
        fi
        mv "$dest.part" "$dest" && echo "ok   $dest"
    done < "$list"
done
exit $failed
