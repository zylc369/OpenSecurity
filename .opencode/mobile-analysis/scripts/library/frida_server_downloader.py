"""Shared frida-server download and extraction utilities (device-independent)."""

import lzma
import subprocess
import sys
from pathlib import Path

from . import config
from .errors import BwFridaError, ErrorCode
from .log import log


class FridaDownloadError(BwFridaError):
    def __init__(self, message: str, error_code: ErrorCode) -> None:
        super().__init__(message, error_code)


def prepare_frida_server(upgrade: bool = False) -> Path | None:
    """Ensure a local frida-server binary is available.

    Returns the Path to the extracted binary, or None if it already exists
    (i.e. the caller should check install_record before deciding to push).
    """
    local = _find_local_download()
    if local is not None and not upgrade:
        log.info("本地已存在 frida-server: %s", local)
        return local

    archive = _download_frida_server()
    return _extract_archive(archive)


def _find_local_download() -> Path | None:
    if not config.FRIDA_DOWNLOAD_DIR.exists():
        log.info("下载目录不存在: %s", config.FRIDA_DOWNLOAD_DIR)
        return None

    candidates = []
    for path in config.FRIDA_DOWNLOAD_DIR.glob(config.FRIDA_SERVER_BINARY_GLOB):
        if path.is_file() and not path.name.endswith((".xz", ".gz", ".bz2")):
            candidates.append(path)

    if not candidates:
        log.info("未找到本地 frida-server 二进制文件: %s", config.FRIDA_DOWNLOAD_DIR)
        return None

    candidates.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    chosen = candidates[0]
    log.info("找到本地 frida-server: %s", chosen)
    return chosen


def _download_frida_server() -> Path:
    config.FRIDA_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    log.info("正在下载 frida-server...")
    result = subprocess.run(
        [
            "bunx", "@zylc369/bw-gh-release-fetch",
            "https://github.com/frida/frida",
            "frida-server-*-android-arm64.*",
            "-o", str(config.FRIDA_DOWNLOAD_DIR),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        msg = f"下载 frida-server 失败:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        log.error(msg)
        raise FridaDownloadError(msg)

    output = result.stdout.strip()
    downloaded_files = set()
    for line in output.splitlines():
        line = line.strip()
        if config.FRIDA_DOWNLOAD_DIR.name in line or "frida-server" in line:
            for potential_path in line.split():
                p = Path(potential_path.strip())
                if p.exists() and "frida-server" in p.name:
                    downloaded_files.add(p)

    if not downloaded_files:
        for path in config.FRIDA_DOWNLOAD_DIR.glob("frida-server-*-android-arm64.*"):
            if path.is_file() and path.name.endswith((".xz", ".gz", ".bz2", ".tar")):
                downloaded_files.add(path)

    if not downloaded_files:
        msg = "下载完成但未找到下载的文件"
        log.error(msg)
        raise FridaDownloadError(msg)

    if len(downloaded_files) > 1:
        msg = (
            "下载了多个文件，预期只下载一个。下载的文件: "
            + ", ".join(str(f) for f in downloaded_files)
        )
        log.error(msg)
        raise FridaDownloadError(msg)

    archive_path = next(iter(downloaded_files))
    log.info("下载完成: %s", archive_path)
    return archive_path


def _extract_archive(archive_path: Path) -> Path:
    log.info("正在解压: %s", archive_path)
    output_path = config.FRIDA_DOWNLOAD_DIR / archive_path.stem
    try:
        with lzma.open(archive_path, "rb") as f_in, open(output_path, "wb") as f_out:
            while chunk := f_in.read(1024 * 1024):
                f_out.write(chunk)
    except Exception as e:
        msg = f"解压失败: {e}"
        log.error(msg)
        raise FridaDownloadError(msg, ErrorCode.EXTRACT_FAILED) from e

    extracted = _find_local_download()
    if extracted is None:
        msg = "解压完成但未找到 frida-server 二进制文件"
        log.error(msg)
        raise FridaDownloadError(msg, ErrorCode.EXTRACT_FAILED)
    log.info("解压成功: %s", extracted)
    return extracted
