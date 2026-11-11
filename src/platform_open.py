# src/platform_open.py
# pyright: reportOptionalMemberAccess=true
import os
import platform
import subprocess

from src.i18n import t


def open_folder(path: str) -> None:
    """Open the given directory in the OS file manager.

    Raises:
        RuntimeError: on unsupported platforms.
        OSError / subprocess.CalledProcessError: on OS-level failures
            (propagated to caller).
    """
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.run(["open", path], check=True)
    elif system == "Linux":
        subprocess.run(["xdg-open", path], check=True)
    else:
        raise RuntimeError(t("platform_open.nicht_unterstuetzt", system=system))
