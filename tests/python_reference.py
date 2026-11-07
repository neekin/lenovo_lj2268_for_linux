#!/usr/bin/env python3
"""Run the unchanged Python filter with a fixed job clock for byte comparisons."""
import os
import runpy
import sys
import time

reference = sys.argv[1]
sys.argv = [reference] + sys.argv[2:]
original_localtime = time.localtime
if hasattr(time, "tzset"):
    time.tzset()
epoch = int(os.environ["LHPL_JOB_EPOCH"])
module = runpy.run_path(reference, run_name="lhpl_reference")
module["time"].localtime = lambda *args: original_localtime(*args) if args else original_localtime(epoch)
raise SystemExit(module["main"]())
