"""Local suspend-inclusive deadlines, independent of wall clock / DB UTC."""

import ctypes
import sys
import time

from output_guardian.model import Closed

if sys.platform == "darwin":

    class _Timebase(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

    _system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    _system.mach_continuous_time.restype = ctypes.c_uint64
    _base = _Timebase()
    if _system.mach_timebase_info(ctypes.byref(_base)) or not _base.denom:
        raise Closed("OUTPUT_FENCE_UNPROVEN")
    _scale = _base.numer / _base.denom / 1e9


def suspend_clock():
    if sys.platform == "darwin":
        return _system.mach_continuous_time() * _scale
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    # Do not silently substitute a clock that excludes machine suspension.
    raise Closed("OUTPUT_FENCE_UNPROVEN")
