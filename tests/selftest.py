#!/usr/bin/env python3
"""Offline ABI/protocol checks: no cupsd or physical printer is contacted."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import struct
import subprocess
import tempfile


def raster(width=64, height=32):
    header = bytearray(1800)
    header[:4] = b"3SaR"
    struct.pack_into("<II", header, 0x164, 595, 842)
    for offset, value in [(0x178, width), (0x17c, height), (0x188, 8), (0x18c, width)]:
        struct.pack_into("<I", header, offset, value)
    pixels = bytes(0 if (x // 8 + y // 8) % 2 else 255
                   for y in range(height) for x in range(width))
    return bytes(header) + pixels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--filter", required=True)
    args = ap.parse_args()
    library = str(Path(args.library).resolve())
    driver = str(Path(args.filter).resolve())
    os.environ["LHPL_LIB"] = library
    mod = runpy.run_path(driver, run_name="lj2268_selftest")
    encoder = mod["JbigEncoder"]()
    bitmap = bytes([0xAA, 0x55] * (512 * 32 // 16))
    encoded, stripes = encoder.encode(bitmap, 512, 32)
    assert len(encoded) >= 22 and stripes == 1
    assert struct.unpack_from(">II", encoded, 4) == (512, 32)
    # Frozen from the real ARMv7/glibc encoder: 32/64-bit builds must agree.
    assert hashlib.sha256(encoded).hexdigest() == "2c70b99a24fcbfb91adf2b71f28ebb5060e6544520e8e1ff442052eab4e14434"
    noise = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(2048))
    large, _ = encoder.encode(noise, 512, 1024)
    assert len(large) > 65535
    template = mod["pick_template"]((595, 842), 512, 1024)
    frame = mod["build_sp_header"](template, 512, 1024, len(large))
    assert struct.unpack_from("<I", frame, 0x0e)[0] == len(large)
    assert struct.unpack_from("<I", frame, 0x12)[0] == len(large)
    page = mod["parse_raster"](raster())[0]
    fast = mod["to_1bpp"](page, 64, 32)
    # An independent bit-packing oracle catches inverted or shifted pixels.
    expected = bytes(sum((0x80 >> bit) if value < 128 else 0
                         for bit, value in enumerate(page["data"][p:p + 8]))
                     for p in range(0, len(page["data"]), 8))
    assert fast == expected
    # The same input must produce two complete page frames, including the corrected @ep.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "two-pages.raster"
        path.write_bytes(raster() + raster())
        result = subprocess.run(["python3", driver, "1", "selftest", "ABI check", "1", "", str(path)],
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = result.stdout
    for command in (b"\x1bLH@sp", b"\x1bLH@ep"):
        positions = [i for i in range(len(output)) if output.startswith(command, i)]
        assert len(positions) == 2, (command, positions)
        for pos in positions:
            frame = output[pos:pos + 64]
            checksum = 0
            for value in frame:
                checksum ^= value
            assert len(frame) == 64 and checksum == 0
            if command.endswith(b"sp"):
                length = struct.unpack_from("<I", frame, 6 + 0x0e)[0]
                assert output[pos + 64 + length:pos + 64 + length + 6] == b"\x1bLH@ep"
    assert output.endswith(b"@PJL EOJ\r\n")
    print(json.dumps({"architecture": platform.machine(), "native_library": "loaded",
                      "jbig_sha256": hashlib.sha256(encoded).hexdigest(),
                      "pillow": mod["_PillowImage"] is not None,
                      "two_page_frame_checks": "passed", "physical_print": False}))


if __name__ == "__main__":
    main()
