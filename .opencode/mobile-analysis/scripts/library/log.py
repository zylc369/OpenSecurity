import logging
import sys
from pathlib import Path

_LOG_FILE = Path("~/bw-frida/frida.log").expanduser()
_LOG_FORMAT = logging.Formatter("[%(name)s] %(asctime)s %(levelname)s: %(message)s")


def get_logger(name: str = "frida-launcher") -> logging.Logger:
    """Returns a configured logger that outputs to stderr and ~/bw-frida/frida.log."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(_LOG_FORMAT)
        logger.addHandler(stderr_handler)

        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(_LOG_FORMAT)
        logger.addHandler(file_handler)

        logger.setLevel(logging.INFO)
    return logger


# Module-level convenience logger
log = get_logger()
