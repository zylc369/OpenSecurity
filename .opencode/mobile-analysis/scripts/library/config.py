import string
from pathlib import Path

# Directory layout
LIBRARY_DIR = Path(__file__).resolve().parent  # library/
SCRIPTS_DIR = LIBRARY_DIR.parent  # scripts/

# Frida data directories（运行时数据，在用户 home 下）
FRIDA_BASE_DIR = Path("~/bw-frida/frida-server").expanduser()
FRIDA_DOWNLOAD_DIR = FRIDA_BASE_DIR / "download"
INSTALL_RECORD_PATH = FRIDA_BASE_DIR / "install_record.json"
FRIDA_DB_PATH = FRIDA_BASE_DIR / "frida.db"

# Frida server patterns
FRIDA_SERVER_GLOB_PATTERN = "frida-server-*-android-arm64*"
FRIDA_SERVER_BINARY_GLOB = "frida-server-*-android-arm64"

# ADB install location on Android
ADB_INSTALL_ROOT = "/data/local/tmp"

# Port configuration
DEFAULT_PORT_START = 6655
PORT_MAX_TRIES = 100

# Random name configuration
RANDOM_NAME_MIN_LEN = 6
RANDOM_NAME_MAX_LEN = 8
RANDOM_NAME_CHARSET = string.ascii_lowercase + string.digits
