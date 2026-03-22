"""Extract WeChat database encryption key from process memory (Windows only).

The key is found by scanning the WeChat.exe process memory for a pattern
matching the SQLCipher encryption key format. This is a read-only operation
that does not modify the WeChat process.
"""

from __future__ import annotations

import ctypes
import logging
import re
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

# Key pattern: x'<64 hex chars for 32-byte enc_key><32 hex chars for 16-byte salt>'
KEY_PATTERN = re.compile(rb"x'([0-9a-f]{64})([0-9a-f]{32})'", re.IGNORECASE)
KEY_SIZE = 32


def find_wechat_key() -> bytes | None:
    """Extract encryption key from WeChat process memory.

    Scans all readable memory regions of the WeChat.exe process for the
    SQLCipher key pattern. Returns the 32-byte encryption key or None.

    Only works on Windows. Returns None on other platforms.
    """
    try:
        import ctypes.wintypes
    except (ImportError, OSError):
        logger.info("Key extraction only available on Windows")
        return None

    pid = _find_wechat_pid()
    if not pid:
        logger.error("WeChat process not found")
        return None

    return _scan_process_memory(pid)


def _find_wechat_pid() -> int | None:
    """Find the PID of WeChat.exe using Windows API."""
    try:
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_INFORMATION = 0x0400
        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.wintypes.DWORD),
                ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return None

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

        try:
            if kernel32.Process32First(snapshot, ctypes.byref(pe)):
                while True:
                    name = pe.szExeFile.decode("utf-8", errors="ignore").lower()
                    if name == "wechat.exe":
                        return pe.th32ProcessID
                    if not kernel32.Process32Next(snapshot, ctypes.byref(pe)):
                        break
        finally:
            kernel32.CloseHandle(snapshot)

    except Exception as e:
        logger.error("Failed to find WeChat PID: %s", e)

    return None


def _scan_process_memory(pid: int) -> bytes | None:
    """Scan process memory for the encryption key pattern."""
    try:
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_VM_READ = 0x0010
        PROCESS_QUERY_INFORMATION = 0x0400
        MEM_COMMIT = 0x1000
        PAGE_READABLE = {0x02, 0x04, 0x06, 0x20, 0x40, 0x80}

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", ctypes.wintypes.DWORD),
                ("Protect", ctypes.wintypes.DWORD),
                ("Type", ctypes.wintypes.DWORD),
            ]

        process = kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid,
        )
        if not process:
            logger.error("Cannot open WeChat process (run as admin?)")
            return None

        try:
            address = 0
            max_address = 0x7FFFFFFFFFFFFFFF  # 64-bit
            mbi = MEMORY_BASIC_INFORMATION()
            buf = ctypes.create_string_buffer(4096)
            bytes_read = ctypes.c_size_t()

            while address < max_address:
                result = kernel32.VirtualQueryEx(
                    process, ctypes.c_void_p(address),
                    ctypes.byref(mbi), ctypes.sizeof(mbi),
                )
                if result == 0:
                    break

                if (mbi.State == MEM_COMMIT
                        and mbi.Protect in PAGE_READABLE
                        and mbi.RegionSize <= 100 * 1024 * 1024):  # skip >100MB regions
                    key = _search_region(
                        process, kernel32, address, mbi.RegionSize,
                    )
                    if key:
                        return key

                address += mbi.RegionSize

        finally:
            kernel32.CloseHandle(process)

    except Exception as e:
        logger.error("Memory scan failed: %s", e)

    return None


def _search_region(
    process, kernel32, base_address: int, region_size: int,
) -> bytes | None:
    """Search a memory region for the key pattern."""
    CHUNK_SIZE = 1024 * 1024  # Read 1MB at a time
    bytes_read = ctypes.c_size_t()

    offset = 0
    overlap = 200  # overlap between chunks to catch patterns at boundaries

    while offset < region_size:
        read_size = min(CHUNK_SIZE, region_size - offset)
        buf = ctypes.create_string_buffer(read_size)

        success = kernel32.ReadProcessMemory(
            process,
            ctypes.c_void_p(base_address + offset),
            buf, read_size,
            ctypes.byref(bytes_read),
        )

        if success and bytes_read.value > 0:
            data = buf.raw[:bytes_read.value]
            match = KEY_PATTERN.search(data)
            if match:
                key_hex = match.group(1)
                key = bytes.fromhex(key_hex.decode("ascii"))
                logger.info(
                    "Found potential key at 0x%x+0x%x",
                    base_address, offset + match.start(),
                )
                return key

        offset += read_size - overlap if read_size > overlap else read_size

    return None


def find_wechat_data_dir() -> Path | None:
    """Auto-detect WeChat data directory on Windows.

    Checks common locations for WeChat's 'Msg' folder containing encrypted DBs.
    """
    import os

    # Common WeChat data paths
    documents = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "WeChat Files"
    if not documents.exists():
        documents = Path(os.environ.get("APPDATA", "")) / "Tencent" / "WeChat"

    if not documents.exists():
        return None

    # Find the user's data directory (named after wxid)
    for user_dir in documents.iterdir():
        if user_dir.is_dir():
            msg_dir = user_dir / "Msg"
            if msg_dir.exists():
                return msg_dir

    return None
