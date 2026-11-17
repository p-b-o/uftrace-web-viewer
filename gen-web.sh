#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname $(readlink -f $0))

if [ -z "${DISABLE_CONTAINER_CHECK:-}" ]; then
    $script_dir/container.sh $script_dir/gen-web.sh "$@"
    exit 0
fi

web=$script_dir/web
data=$(pwd)/uftrace.data/web

if [ ! -d $data ]; then
    trap "rm -rf $data" EXIT
    $web/uftrace-web-trace.py "$@"
    rsync -a \
        /usr/share/perfetto \
        $web/style.css $web/uftrace-web-viewer.js $web/index.html \
        $data/
    trap - EXIT
fi
