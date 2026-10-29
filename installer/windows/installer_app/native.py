import os
import subprocess


def hide_worker_consoles():
    """All native helpers run hidden; the only interactive surface is our GUI."""
    if os.name != 'nt':
        return
    original = subprocess.Popen

    class HiddenPopen(original):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
            super().__init__(*args, **kwargs)

    subprocess.Popen = HiddenPopen
