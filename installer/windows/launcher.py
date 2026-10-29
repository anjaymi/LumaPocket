"""Windowed EXE entry point and private worker dispatcher."""
import ctypes
import io
import os
from pathlib import Path
import sys


def open_pipe_streams():
    if os.name != 'nt':
        return
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    current_process = kernel.GetCurrentProcess()
    for name, number, flags, mode in (('stdin', -10, os.O_RDONLY, 'rb'),
                                       ('stdout', -11, os.O_WRONLY, 'wb')):
        handle = kernel.GetStdHandle(number & 0xffffffff)
        if handle and handle != ctypes.c_void_p(-1).value:
            duplicate = wintypes.HANDLE()
            if not kernel.DuplicateHandle(current_process, handle, current_process, ctypes.byref(duplicate), 0, False, 2):
                raise OSError('worker_pipe_unavailable')
            fd = msvcrt.open_osfhandle(duplicate.value, flags | os.O_BINARY)
            stream = os.fdopen(fd, mode, buffering=0)
            setattr(sys, name, io.TextIOWrapper(stream, encoding='utf-8', errors='replace', write_through=True))
    sys.stderr = sys.stdout


def main():
    if '--worker' in sys.argv:
        open_pipe_streams()
        from installer_app.backend import main as worker
        return worker(sys.argv[sys.argv.index('--worker') + 1:])
    if '--selftest' in sys.argv:
        from installer_app.selftest import run
        return run(Path(sys.argv[sys.argv.index('--selftest') + 1]))
    from installer_app.ui import main as show
    ipa = None
    if '--ipa' in sys.argv and sys.argv.index('--ipa') + 1 < len(sys.argv):
        ipa = Path(sys.argv[sys.argv.index('--ipa') + 1])
    show(initial_ipa=ipa)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
