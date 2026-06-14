import fcntl
import json
from pathlib import Path

from . import config
from .log import log


def ensure_record_dir() -> None:
    """Create ~/bw-frida/frida-server/ directory if it doesn't exist."""
    config.FRIDA_BASE_DIR.mkdir(parents=True, exist_ok=True)


def read_record() -> dict:
    """Read install_record.json. Returns {} if missing or malformed."""
    if not config.INSTALL_RECORD_PATH.exists():
        return {}
    try:
        with open(config.INSTALL_RECORD_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("install_record.json is malformed, resetting: %s", e)
        return {}


def write_record(data: dict) -> None:
    """Write full dict to install_record.json with fcntl.LOCK_EX."""
    ensure_record_dir()
    with open(config.INSTALL_RECORD_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def get_device_record(device_id: str) -> dict | None:
    """Return record for a specific device, or None."""
    record = read_record()
    return record.get(device_id)


def update_device_record(device_id: str, **fields) -> None:
    """Atomic read-modify-write: update fields for a device. Uses fcntl file locking."""
    ensure_record_dir()
    with open(config.INSTALL_RECORD_PATH, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                data = {}
            if device_id not in data:
                data[device_id] = {}
            data[device_id].update(
                {k: v for k, v in fields.items() if v is not None}
            )
            for k in [k for k, v in fields.items() if v is None]:
                data[device_id].pop(k, None)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def delete_device_record(device_id: str) -> None:
    """Atomic read-modify-write: remove a device entry. Uses fcntl file locking."""
    if not config.INSTALL_RECORD_PATH.exists():
        return
    ensure_record_dir()
    with open(config.INSTALL_RECORD_PATH, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                data = {}
            data.pop(device_id, None)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
