#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname $(readlink -f $0))

if [ -z "${DISABLE_CONTAINER_CHECK:-}" ]; then
    $script_dir/container.sh $script_dir/uftrace-web-viewer.sh "$@"
    exit 0
fi

$script_dir/gen-web.sh "$@"

data=$(pwd)/uftrace.data/web
pushd $data
echo --------------------------------------------------
echo "Trace available at: http://127.0.0.1:8000/?action=view-trace&trace=./trace.json"
echo "Trace available at: http://$(hostname):8000/?action=view-trace&trace=./trace.json"
echo --------------------------------------------------
python3 -m http.server > /dev/null
popd
