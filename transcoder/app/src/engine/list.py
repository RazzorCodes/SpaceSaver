import os
from pathlib import Path
from threading import Event
from typing import Callable

from misc.logger import logger


def list_path(
    path: Path,
    ext_wl: list[str],
    cancel: Event | None = None,
    on_item: Callable[[Path], None] | None = None,
) -> list[Path]:
    if cancel and cancel.is_set():
        return []

    logger.debug(f"listing path: {path}")

    # FIX: Added the missing colon at the end of this line
    if not path.is_dir():
        logger.warning(f"attempted to list non-existent or invalid path: {path}")
        return []

    lst = []

    # Ensure all extensions in the whitelist are lowercase to match the check later
    ext_wl = [ext.lower() for ext in ext_wl]

    for root, _dirs, files in os.walk(path):
        if cancel and cancel.is_set():
            return lst

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ext_wl:
                continue

            # FIX: Renamed 'path' to 'file_path' so it doesn't shadow the input argument.
            # Also used pathlib's native '/' operator for cleaner path joining.
            file_path = Path(root) / fname
            lst.append(file_path)

            # THE ADDITION: Trigger the callback for the database update
            if on_item:
                on_item(file_path)

    return lst
