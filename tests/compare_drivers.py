#!/usr/bin/env python3
"""Full-stream byte parity and same-raster benchmarks; never submits print jobs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def noise(size):
    return (b"".join(hashlib.sha256(str(i).encode()).digest() for i in range((size + 31) // 32)))[:size]


def page(w=65, h=33, bpp=8, paper=(595, 842), padding=0, header_size=1800, magic=True, pixels=None):
    stride = (w * bpp + 7) // 8 + padding
    header = bytearray(header_size)
    shift = 0 if magic else -4
    if magic:
        header[:4] = b"3SaR"
    struct.pack_into("<II", header, 0x164 + shift, *paper)
    for offset, value in ((0x178, w), (0x17c, h), (0x188, bpp), (0x18c, stride)):
        struct.pack_into("<I", header, offset + shift, value)
    pixels = noise(stride * h) if pixels is None else pixels
    assert len(pixels) == stride * h
    return bytes(header) + pixels


def invoke(command, fixture, env, use_stdin=False):
    options = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": env, "timeout": 90}
    if use_stdin:
        options["input"] = fixture.read_bytes()
        command = command + ["-"]
    else:
        command = command + [str(fixture)]
    return subprocess.run(command, **options)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--reference", default=str(ROOT / "rastertolkpl"))
    parser.add_argument("--raster", help="Real raster, used for parity and benchmarks")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--report", default=str(ROOT / "build/c-parity.json"))
    args = parser.parse_args()
    reference = Path(args.reference).resolve()
    native = Path(args.native).resolve()
    env = dict(os.environ, LHPL_LIB=str(Path(args.library).resolve()),
               LHPL_JOB_EPOCH="1700000000", TZ="UTC", PYTHONIOENCODING="utf-8")
    for key in ("LHPL_DITHER", "LHPL_THRESHOLD", "LHPL_EP_HEX", "LHPL_DEBUG"):
        env.pop(key, None)
    job = ["1", "parity-user", "中英文 parity test", "3", "PageSize=A4"]
    py = [sys.executable, str(ROOT / "tests/python_reference.py"), str(reference)] + job
    c = [str(native)] + job
    cases = []
    for threshold in (0, 1, 127, 128, 254, 255):
        cases.append(("gray-threshold-%d" % threshold, page(padding=5), {"LHPL_THRESHOLD": str(threshold)}, False))
    for w in (1, 7, 8, 9, 511, 512, 513):
        cases.append(("width-%d" % w, page(w=w), {}, False))
    for bpp in (1, 24, 32):
        cases.append(("bpp-%d" % bpp, page(w=64, bpp=bpp, padding=0), {}, False))
    for threshold in (0, 128, 255):
        cases.append(("dither-%d" % threshold, page(padding=3),
                      {"LHPL_DITHER": "1", "LHPL_THRESHOLD": str(threshold)}, False))
    cases.append(("rgb-dither-reference-behavior", page(bpp=24, padding=5), {"LHPL_DITHER": "1"}, False))
    papers = {"A4": (595, 842), "A5": (420, 595), "A6": (297, 420),
              "B5": (516, 729), "B6": (363, 516), "Letter": (612, 792), "Executive": (522, 756)}
    for name, size in papers.items():
        cases.append((name, page(paper=size), {}, False))
        cases.append((name + "-landscape", page(paper=size[::-1]), {}, False))
    cases.append(("nearest-custom-paper", page(paper=(600, 850)), {}, False))
    cases.extend([
        ("two-linux-pages", page() + page(w=80, paper=(420, 595)), {}, False),
        ("two-macos-pages", page() + page(w=80, header_size=1796, magic=False), {}, False),
        ("mixed-three-pages", page() + page(w=80, header_size=1796, magic=False) + page(w=96), {}, False),
        ("stdin", page(), {}, True),
        ("1bpp-padded-reference-behavior", page(w=65, bpp=1, padding=3), {}, False),
    ])
    for size in (1804, 1816, 1832):
        cases.append(("extended-first-header-%d" % size, page(header_size=size), {}, False))
    cases.append(("large-jbig-length", page(w=512, h=1024), {}, False))
    cases.append(("ep-override", page(), {"LHPL_EP_HEX": " ".join(["12"] * 58)}, False))
    if args.raster:
        cases.append(("real-cups-raster", Path(args.raster).read_bytes(), {}, False))
    report = {"architecture": platform.machine(), "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
              "comparison": "complete stdout byte-for-byte; same job metadata, hostname and fixed clock",
              "physical_print": False, "cases": [], "negative_cases": []}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fixture = tmp / "input.raster"
        for name, data, extra, stdin in cases:
            fixture.write_bytes(data)
            current_env = dict(env, **extra)
            a = invoke(py, fixture, current_env, stdin)
            b = invoke(c, fixture, current_env, stdin)
            if a.returncode or b.returncode or a.stdout != b.stdout:
                (tmp / "python.prn").write_bytes(a.stdout)
                (tmp / "c.prn").write_bytes(b.stdout)
                offset = next((i for i, (x, y) in enumerate(zip(a.stdout, b.stdout)) if x != y), None)
                raise AssertionError({"case": name, "returncodes": [a.returncode, b.returncode],
                                      "lengths": [len(a.stdout), len(b.stdout)], "first_difference": offset,
                                      "python_stderr": a.stderr.decode(errors="replace")[-400:],
                                      "c_stderr": b.stderr.decode(errors="replace")[-400:]})
            payload = a.stdout[a.stdout.index(b"\x1bLH@sj"):]
            report["cases"].append({"name": name, "bytes": len(a.stdout), "sha256": hashlib.sha256(a.stdout).hexdigest(),
                                    "printer_payload_sha256": hashlib.sha256(payload).hexdigest()})
        for copies in ("0", "1", "-1", "invalid", "0007"):
            fixture.write_bytes(page())
            a = invoke(py[:6] + [copies, job[-1]], fixture, env)
            b = invoke(c[:4] + [copies, job[-1]], fixture, env)
            assert a.returncode == b.returncode == 0 and a.stdout == b.stdout, copies
            payload = a.stdout[a.stdout.index(b"\x1bLH@sj"):]
            report["cases"].append({"name": "copies-" + copies, "bytes": len(a.stdout),
                                    "printer_payload_sha256": hashlib.sha256(payload).hexdigest()})
        invalid = {"empty": b"", "truncated-header": b"3SaR" + bytes(100),
                   "truncated-page": page()[:-100], "16K-unverified-template": page(paper=(524, 737)),
                   "unsupported-pixel-format": page(bpp=16), "truncated-second-page": page() + page()[:-100]}
        for name, data in invalid.items():
            fixture.write_bytes(data)
            result = invoke(c, fixture, env)
            assert result.returncode != 0 and not result.stdout, (name, result.stderr)
            assert b"AddressSanitizer" not in result.stderr and b"runtime error:" not in result.stderr, result.stderr
            report["negative_cases"].append(name)
        fixture.write_bytes(page())
        for key, value in (("LHPL_EP_HEX", "1"), ("LHPL_EP_HEX", "00" * 57), ("LHPL_THRESHOLD", "256")):
            result = invoke(c, fixture, dict(env, **{key: value}))
            assert result.returncode != 0 and not result.stdout, (key, value)
            assert b"AddressSanitizer" not in result.stderr and b"runtime error:" not in result.stderr, result.stderr
            report["negative_cases"].append(key + "=" + value)
        if args.benchmark:
            if not args.raster or args.repeats < 3:
                raise SystemExit("Benchmark requires --raster and at least 3 repeats")
            results = {}
            expected = None
            for name, command in (("python", py), ("c", c)):
                times, memory = [], []
                for sample in range(args.repeats + 1):
                    usage = tmp / "time.txt"
                    output = tmp / "output.prn"
                    start = time.perf_counter()
                    with output.open("wb") as out:
                        process = subprocess.run(["/usr/bin/time", "-f", "%M", "-o", str(usage)] + command + [str(Path(args.raster).resolve())],
                                                 stdout=out, stderr=subprocess.PIPE, env=env, timeout=90)
                    elapsed = time.perf_counter() - start
                    assert process.returncode == 0, process.stderr.decode(errors="replace")
                    digest = hashlib.sha256(output.read_bytes()).hexdigest()
                    if expected is None:
                        expected = digest
                    assert digest == expected, (name, sample, "benchmark output differs")
                    if sample:  # one warm-up run per implementation
                        times.append(elapsed)
                        memory.append(int(usage.read_text().strip()))
                results[name] = {"seconds": times, "median_seconds": statistics.median(times),
                                 "peak_rss_kib": memory, "median_peak_rss_kib": statistics.median(memory)}
            report["benchmark"] = {"raster_sha256": hashlib.sha256(Path(args.raster).read_bytes()).hexdigest(),
                                   "raster_bytes": Path(args.raster).stat().st_size, "output_sha256": expected,
                                   "includes_pdf_render": False, "warmup_per_implementation": 1,
                                   "runs": results, "speedup": results["python"]["median_seconds"] / results["c"]["median_seconds"]}
    report["passed_cases"] = len(report["cases"])
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("cases",)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
