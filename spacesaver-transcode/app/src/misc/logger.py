import logging

from colorlog import ColoredFormatter

TRACE_LEVEL = 15  # ... info - trace - debug
logging.addLevelName(TRACE_LEVEL, "TRACE")


class LoggerEx(logging.Logger):
    def trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(TRACE_LEVEL):
            kwargs.setdefault("stacklevel", 2)
            self._log(TRACE_LEVEL, msg, args, **kwargs)


logging.setLoggerClass(LoggerEx)

# color formatter
formatter = ColoredFormatter(
    "%(log_color)s[%(asctime)s] [%(filename)s:%(lineno)d] [%(levelname)s] %(message)s",
    datefmt="%d/%m/%y %H:%M:%S",
    log_colors={
        "TRACE": "white",
        "DEBUG": "blue",
        "INFO": "white",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    },
)

handler = logging.StreamHandler()
handler.setFormatter(fmt=formatter)

logger = LoggerEx(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)
