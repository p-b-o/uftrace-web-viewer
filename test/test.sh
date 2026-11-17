#!/usr/bin/env bash

set -euo pipefail
set -x

script_dir=$(dirname $(readlink -f $0))

if [ -z "${DISABLE_CONTAINER_CHECK:-}" ]; then
    $script_dir/../container.sh $script_dir/test.sh "$@"
    exit 0
fi

tmp=$(mktemp -d)
trap "rm -rf $tmp" EXIT

rm -rf uftrace.data trace.gz
gcc -pg -g -O0 $script_dir/nested.c -o $tmp/nested
uftrace record --srcline --clock=realtime $tmp/nested | ts "%.s" > $tmp/exec.log
cat $tmp/exec.log
mv $tmp/exec.log uftrace.data/

# full trace
$script_dir/../perfetto.sh 0 9999999999 uftrace.data/trace.gz
test -s uftrace.data/trace.gz

$script_dir/../gen-web.sh

web=uftrace.data/web
test -f $web/index.html
test -n "$(find $web/sources -name nested.c)"
python3 - $web/trace.json <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
labels = [e["label"] for e in data["events"]]
assert labels == ["a", "b", "c", "d"], labels
assert data["traces"], "no traces"
PY
ls $web/traces/*.gz
uftrace replay --no-pager
