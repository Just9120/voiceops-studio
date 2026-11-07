"""Best-effort hardware inventory. Local paths are never part of the payload."""
import ctypes
import os
import platform
import shutil
from uuid import UUID


def _ram_bytes():
    if os.name != "nt":
        return None

    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in ("total", "available", "page", "page_free", "virtual", "virtual_free", "extended")
        ]

    status = Memory()
    status.length = ctypes.sizeof(status)
    return status.total if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)) else None


def _windows_gpus():
    if os.name != "nt":
        return []

    class Adapter(ctypes.Structure):
        _fields_ = [("name", ctypes.c_wchar * 128)] + [
            (name, ctypes.c_uint32) for name in ("vendor", "device", "subsystem", "revision")
        ] + [(name, ctypes.c_size_t) for name in ("vram", "system", "shared")] + [
            ("luid_low", ctypes.c_uint32), ("luid_high", ctypes.c_int32), ("flags", ctypes.c_uint32)
        ]

    def method(pointer, index, result, *types):
        vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *types)(vtable[index])

    try:
        create = ctypes.WinDLL("dxgi.dll", winmode=0x800).CreateDXGIFactory1
        create.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        iid = (ctypes.c_ubyte * 16).from_buffer_copy(UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
        factory = ctypes.c_void_p()
        if create(ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory:
            return []
    except (OSError, AttributeError):
        return []
    adapters = []
    try:
        enum = method(factory, 12, ctypes.c_long, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))
        for index in range(8):
            pointer = ctypes.c_void_p()
            if enum(factory, index, ctypes.byref(pointer)) != 0 or not pointer:
                break
            try:
                description = Adapter()
                read = method(pointer, 10, ctypes.c_long, ctypes.POINTER(Adapter))
                if read(pointer, ctypes.byref(description)) == 0 and not description.flags & 2 and description.name.strip():
                    adapters.append({"name": description.name.strip()[:120], "vram_bytes": description.vram or None})
            finally:
                method(pointer, 2, ctypes.c_ulong)(pointer)
    finally:
        method(factory, 2, ctypes.c_ulong)(factory)
    return adapters


def hardware_inventory(disk):
    try:
        available = shutil.disk_usage(disk).free if disk is not None else None
    except OSError:
        available = None
    return {"cpu": (platform.processor() or platform.machine() or "x64")[:120], "cpu_threads": os.cpu_count(),
            "ram_bytes": _ram_bytes(), "gpus": _windows_gpus(), "disk_free_bytes": available,
            "execution": ["cpu"]}
