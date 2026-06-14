"""Common exception base class for all bw-frida errors."""

from __future__ import annotations

import enum


@enum.unique
class ErrorCode(enum.Enum):
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_NOT_CONNECTED = "DEVICE_NOT_CONNECTED"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    INSTALL_RECORD_INVALID = "INSTALL_RECORD_INVALID"
    SERVER_NOT_INSTALLED = "SERVER_NOT_INSTALLED"
    SERVER_NOT_RUNNING = "SERVER_NOT_RUNNING"
    SERVER_START_FAILED = "SERVER_START_FAILED"
    SERVER_STOP_FAILED = "SERVER_STOP_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    EXTRACT_FAILED = "EXTRACT_FAILED"
    ADB_CMD_FAILED = "ADB_CMD_FAILED"
    PORT_FORWARD_FAILED = "PORT_FORWARD_FAILED"


class BwFridaError(Exception):
    def __init__(self, message: str, error_code: ErrorCode) -> None:
        self.message = message
        self.error_code = error_code
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.error_code.value}] {self.message}"
