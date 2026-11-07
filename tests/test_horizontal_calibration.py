#!/usr/bin/env python3
"""Verify packed-pixel translation against an independent per-pixel oracle.

The baseline encoder runs with calibration disabled. Its zero-shift output is
separately verified against the unchanged Python reference. No jobs are printed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parity_fixtures', ROOT / 'tests/compare_drivers.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
args_parser = argparse.ArgumentParser()
args_parser.add_argument('--native', required=True)
args_parser.add_argument('--baseline', help='Uncalibrated baseline executable; defaults to --native')
args_parser.add_argument('--raster')
args_parser.add_argument('--real-shift-dots', type=int, default=-71)
args_parser.add_argument('--real-only', action='store_true')
args_parser.add_argument('--report', required=True)
args = args_parser.parse_args()
args.baseline = args.baseline or args.native
if args.real_only and not args.raster:
    args_parser.error('--real-only requires --raster')
env = {k: v for k, v in os.environ.items() if not k.startswith('LHPL_')}
env.update(TZ='UTC', LHPL_JOB_EPOCH='1700000000')
job = ['1', 'calibration', 'Chinese and English calibration', '1', 'PageSize=A4']
bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def invoke(exe, raster, shift=None, dither=False):
    current = dict(env)
    if shift is not None:
        current['LHPL_X_SHIFT_DOTS'] = str(shift)
    if dither:
        current['LHPL_DITHER'] = '1'
    return subprocess.run([exe] + job + [str(raster)], env=current,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)


def oracle_pixels(data, width, height, bpp, stride, dither):
    image = []
    for y in range(height):
        row = data[y * stride:(y + 1) * stride]
        if bpp == 1:
            image.append([bool(row[x // 8] & (0x80 >> (x % 8))) for x in range(width)])
        elif bpp == 8:
            image.append([row[x] < 128 + (bayer[y % 4][x % 4] - 8 if dither else 0)
                          for x in range(width)])
        else:
            channels = bpp // 8
            image.append([(row[x * channels] * 299 + row[x * channels + 1] * 587
                           + row[x * channels + 2] * 114) // 1000 < 128
                          for x in range(width)])
    return image


def shifted_packed(image, shift):
    width = len(image[0])
    stride = (width + 7) // 8
    output = bytearray(stride * len(image))
    for y, row in enumerate(image):
        for x in range(width):
            source = x - shift
            if 0 <= source < width and row[source]:
                output[y * stride + x // 8] |= 0x80 >> (x % 8)
    return bytes(output)


report = {'comparison': 'calibrated output vs uncalibrated encoding of independently shifted pixels',
          'positive_cases': 0, 'negative_cases': 0, 'physical_print': False}
with tempfile.TemporaryDirectory() as directory:
    tmp = Path(directory)
    original, expected = tmp / 'original.raster', tmp / 'expected.raster'
    for width in ([] if args.real_only else [1, 7, 8, 9, 65, 511, 512, 513]):
        for bpp in [1, 8, 24, 32]:
            height = 13
            padding = 0 if bpp == 1 else 3
            stride = (width * bpp + 7) // 8 + padding
            pixels = fixtures.noise(stride * height)
            original.write_bytes(fixtures.page(w=width, h=height, bpp=bpp,
                                               padding=padding, pixels=pixels))
            for dither in ([False, True] if bpp == 8 else [False]):
                image = oracle_pixels(pixels, width, height, bpp, stride, dither)
                for shift in [-6000, -71, -12, -9, -8, -7, -1, 0, 1, 7, 8, 9, 12, 71, 6000]:
                    result = invoke(args.native, original, shift, dither)
                    assert result.returncode == 0, result.stderr
                    if shift == 0:
                        reference = invoke(args.baseline, original, None, dither)
                    else:
                        expected.write_bytes(fixtures.page(w=width, h=height, bpp=1,
                                                           pixels=shifted_packed(image, shift)))
                        reference = invoke(args.baseline, expected)
                    assert reference.returncode == 0, reference.stderr
                    assert result.stdout == reference.stdout, (width, bpp, dither, shift)
                    report['positive_cases'] += 1
    original.write_bytes(fixtures.page())
    for bad in ([] if args.real_only else ['-6001', '6001', 'abc', '3mm', '71.5', '']):
        result = invoke(args.native, original, bad)
        assert result.returncode != 0 and not result.stdout, (bad, result.stderr)
        assert b'AddressSanitizer' not in result.stderr and b'runtime error:' not in result.stderr
        report['negative_cases'] += 1
    if args.raster:
        data = Path(args.raster).read_bytes()
        assert data[:4] == b'3SaR'
        width, height = struct.unpack_from('<II', data, 0x178)
        bpp, stride = struct.unpack_from('<II', data, 0x188)
        assert bpp == 8 and stride == width and len(data) == 1800 + stride * height
        shift = args.real_shift_dots
        assert abs(shift) < width
        translated = bytearray(data[:1800])
        for y in range(height):
            row = data[1800 + y * stride:1800 + (y + 1) * stride]
            if shift < 0:
                translated.extend(row[-shift:] + bytes([255]) * -shift)
            elif shift > 0:
                translated.extend(bytes([255]) * shift + row[:-shift])
            else:
                translated.extend(row)
        original.write_bytes(data)
        expected.write_bytes(translated)
        result = invoke(args.native, original, shift)
        reference = invoke(args.baseline, expected)
        assert result.returncode == reference.returncode == 0
        assert result.stdout == reference.stdout, 'real test page shift differs'
        table = bytes(int(i < 128) for i in range(256))
        before_black = data[1800:].translate(table).count(1)
        after_black = bytes(translated[1800:]).translate(table).count(1)
        assert before_black == after_black, 'test-page ink was clipped'
        rows = []
        for fraction in [.2, .5, .8]:
            y = int(height * fraction)
            row = translated[1800 + y * stride:1800 + (y + 1) * stride]
            ink = [x for x, pixel in enumerate(row) if pixel < 128]
            rows.append({'row': y, 'ink_pixels': len(ink),
                         'left_pixels': ink[0] if ink else None,
                         'right_pixels': width - 1 - ink[-1] if ink else None})
        report['real_page'] = {'width': width, 'height': height, 'shift_dots': shift,
                               'shift_mm_at_600_dpi': shift * 25.4 / 600,
                               'shifted_output_sha256': hashlib.sha256(result.stdout).hexdigest(),
                               'ink_pixels_preserved': before_black, 'sampled_rows': rows}
Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
