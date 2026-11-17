#!/usr/bin/env python3

import argparse
import itertools
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import typing
import multiprocessing

NANOSEC_IN_ONE_SEC = 10**9


class Event(typing.TypedDict):
    ts: int
    label: str


def get_events(exec_log: str) -> list[Event]:
    events = []
    with open(exec_log) as file:
        for line_str in file:
            orig_line = line_str
            line_str = line_str.strip()
            if len(line_str) == 0:
                continue
            line = line_str.split(" ")
            # seconds, with optional fractional part (up to nanoseconds)
            m = re.match(r"^([0-9]+)(?:\.([0-9]{1,9}))?$", line[0])
            if not m:
                print("ignore line without timestamp: " + orig_line)
                continue
            sec, frac = m.group(1), m.group(2) or ""
            ts = int(sec) * NANOSEC_IN_ONE_SEC + int(frac.ljust(9, "0"))
            line.pop(0)
            label = " ".join(line)
            events.append(Event(ts=ts, label=label))
    if not events:
        raise Exception("no events found in: " + exec_log)
    return events


# struct uftrace_record, from uftrace.h
RECORD_SIZE = 16
RECORD_MAGIC = 0x5
UFTRACE_ENTRY = 0
UFTRACE_EXIT = 1


def parse_record(data: bytes, offset: int) -> typing.Tuple[int, int, int, int]:
    time, bits = struct.unpack_from("<QQ", data, offset)
    rtype = bits & 0x3
    more = (bits >> 2) & 0x1
    magic = (bits >> 3) & 0x7
    return time, rtype, more, magic


def get_task_bounds(path: str) -> typing.Optional[typing.Tuple[int, int]]:
    size = os.path.getsize(path)
    if size < RECORD_SIZE:
        return None
    with open(path, "rb") as f:
        first, _, _, magic = parse_record(f.read(RECORD_SIZE), 0)
        if magic != RECORD_MAGIC:
            raise Exception("invalid first record in: " + path)
        # records are followed by variable length arguments (when more is
        # set), which can't be decoded without arg specs. Thus, search
        # backward from the end for the last valid record (8 bytes aligned).
        chunk_size = 4096
        while True:
            start = max(0, size - chunk_size)
            f.seek(start)
            data = f.read(size - start)
            for pos in range(size - RECORD_SIZE, start - 1, -8):
                time, rtype, more, magic = parse_record(data, pos - start)
                if magic != RECORD_MAGIC or time < first:
                    continue
                if rtype not in (UFTRACE_ENTRY, UFTRACE_EXIT):
                    continue
                # last record ends file, unless it has arguments
                at_end = pos + RECORD_SIZE == size
                if at_end != (more == 0):
                    continue
                return first, time
            if start == 0:
                raise Exception("can't find last record in: " + path)
            chunk_size *= 2


def get_trace_bounds() -> typing.Tuple[int, int]:
    # each task has its own file, with records sorted by time
    bounds = []
    for file in os.listdir("uftrace.data"):
        if not re.match(r"^[0-9]+\.dat$", file):
            continue
        task_bounds = get_task_bounds("uftrace.data/" + file)
        if task_bounds:
            bounds.append(task_bounds)
    if not bounds:
        raise Exception("no records found in uftrace trace")
    first = min(b[0] for b in bounds)
    last = max(b[1] for b in bounds)
    # round to microseconds (like exec.log), as javascript can't represent
    # nanosecond timestamps exactly, and they are used to name subtraces
    first = first // 1000 * 1000
    last = -(-last // 1000) * 1000
    return first, last


def add_trace_bounds(events: list[Event]) -> list[Event]:
    print("retrieve first and last timestamps from uftrace trace")
    first, last = get_trace_bounds()
    return [Event(ts=first, label="START"), *events, Event(ts=last, label="END")]


class Subtrace(typing.TypedDict):
    start: int
    end: int


def sub_traces(events: list[Event], trace_duration: int) -> list[Subtrace]:
    traces = []
    trace_duration *= NANOSEC_IN_ONE_SEC
    first_timestamp = int(events[0]["ts"])
    last_timestamp = int(events[-1]["ts"])
    offset = int(trace_duration / 2)
    ts = first_timestamp + offset
    while ts < last_timestamp + offset:
        start = ts - offset
        end = ts + offset
        has_events = False
        ts += offset
        for e in events:
            if e["ts"] >= start and e["ts"] <= end:
                has_events = True
                break
        if has_events:
            traces.append(Subtrace(start=start, end=end))
    return traces


def generate_one_trace(params: typing.Tuple[Subtrace, str]) -> str:
    trace, traces_dir = params
    ts_start = str(trace["start"])
    start = trace["start"] / NANOSEC_IN_ONE_SEC
    end = trace["end"] / NANOSEC_IN_ONE_SEC
    path = f"{traces_dir}/{ts_start}.gz"
    here = os.getcwd()
    sed_expr = f's#"srcline":"{here}/#"srcline":"#'

    time_range = f"{start}~{end}"

    # replace srcline to remove absolute path, convert chrome to fuchsia
    # trace and compress trace
    cmd = f"uftrace dump --format=chrome --srcline --time-range={start}~{end}"
    cmd += f" | sed -e '{sed_expr}'"
    cmd += f" | c2f | pigz -9 > {path}"
    subprocess.check_call(["bash", "-euc", "-o", "pipefail", cmd])
    return cmd


def generate_traces(traces: list[Subtrace], traces_dir: str) -> None:
    num_workers = multiprocessing.cpu_count()
    num_traces = len(traces)
    print(f"generate {num_traces} traces in parallel with {num_workers} workers")
    with multiprocessing.Pool(num_workers) as p:
        traces_ = zip(traces, itertools.repeat(traces_dir))
        for i, cmd in enumerate(p.imap_unordered(generate_one_trace, traces_)):
            print(f"[{i + 1}/{num_traces}] {cmd}")


def copy_one_source(s: str, sources_dir: str) -> None:
    here = os.getcwd()
    dir = os.path.abspath(os.path.dirname(s))
    if s.startswith(here):
        dest = s.replace(here, sources_dir)
    else:
        dest = sources_dir + "/" + s
    dest_folder = os.path.dirname(dest)
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
    shutil.copyfile(s, dest)


def copy_sources(sources_dir: str) -> None:
    sources = set()
    for file in os.listdir("uftrace.data"):
        file = "uftrace.data/" + file
        if not file.endswith(".dbg"):
            continue
        with open(file) as dbg:
            for line_str in dbg:
                if not line_str.startswith("L:"):
                    continue
                line = line_str.strip().split(" ")
                source = line[-1]
                if os.path.exists(source):
                    sources.add(source)
    print(f"copy sources to {sources_dir}")
    for s in sources:
        abs_s = os.path.abspath(s)
        real_s = os.path.realpath(s)
        copy_one_source(abs_s, sources_dir)
        # source can be on a symlink
        if abs_s != real_s:
            copy_one_source(real_s, sources_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="uftrace-web-viewer",
        description="explore uftrace trace",
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="show this help message and exit",
    )
    parser.add_argument(
        "exec_log",
        nargs="?",
        default="uftrace.data/exec.log",
        help="log of execution with timestamps",
    )
    parser.add_argument(
        "--trace-duration",
        type=float,
        default=5,
        help="duration for one partial trace (seconds)",
    )
    parser.add_argument(
        "--trace-url",
        default="traces",
        help="base url for traces",
    )
    parser.add_argument(
        "--src-url",
        default="sources",
        help="base url for sources",
    )
    args = parser.parse_args()

    if args.help:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists("uftrace.data"):
        raise Exception("can't find uftrace folder")

    web_dir = "uftrace.data/web"

    events = get_events(args.exec_log)
    events = add_trace_bounds(events)

    traces = sub_traces(events, args.trace_duration)

    traces_dir = web_dir + "/traces"
    if not os.path.exists(traces_dir):
        os.makedirs(traces_dir)
    generate_traces(traces, traces_dir)

    sources_dir = web_dir + "/sources"
    copy_sources(sources_dir)

    json_data = dict(
        events=events, traces=traces, trace_url=args.trace_url, src_url=args.src_url
    )
    json_file = web_dir + "/trace.json"
    with open(json_file, "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"wrote json file {json_file}")


if __name__ == "__main__":
    main()
