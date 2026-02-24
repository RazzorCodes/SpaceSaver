from enum import StrEnum


class Module:
    def setup(self) -> bool:
        return False


class Stage(StrEnum):
    UNKNOWN = "unknown"

    # --- startup ---
    STARTUP = "startup"

    SETUP = "setup"

    # --- work-in-progress ---
    RECOVERING_WORK = ""
    REMOVING_UNFINISHED_WORK = ""

    # --- work loop ---
    READY = "ready"
    # --- activities ---
    SCANNING = ""
    PROBING = ""
    PROCESSING = ""

    # --- unrecoverable ---
    ERROR = "unrecoverable faliure"
