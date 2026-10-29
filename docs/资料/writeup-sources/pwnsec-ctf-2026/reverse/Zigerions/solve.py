#!/usr/bin/env python3
"""End-to-end solver for PwnSec CTF 2026 Zigerions."""

from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import threading
from pathlib import Path

import frida
import pyzipper
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "challenge" / "public.zip"
OUTPUT = ROOT / "output"
PAYLOAD_MARKER = b"<<<PAYLOAD_START>>>"
XOR_KEY = bytes((0xA5, 0x3C, 0xFF, 0x00, 0x55, 0xAA))
RUNTIME_FILES = {
    "AURA.gb": "3141a477c0f440248e71146b2c6f4c582ef0a3a8db30a797df27d272e6812071",
    "svchost": "eaccb6522ec941e1a00ad6360c26888de73da7316892e50b4ab752c81dc9e107",
}

FRIDA_SOURCE = r"""
const shellExecute = Module.findGlobalExportByName('ShellExecuteA');
if (shellExecute === null) {
  send({event: 'error', message: 'ShellExecuteA export not found'});
} else {
  Interceptor.replace(shellExecute, new NativeCallback(function () {
    try {
      const base = Process.mainModule.base;
      const size = base.add(0xd618).readU32();
      const blob = base.add(0xc020).readByteArray(size);
      send({event: 'hidden-elf', size: size}, blob);
    } catch (error) {
      send({event: 'error', message: String(error)});
    }
    return ptr(33);
  }, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer', 'pointer', 'int']));
}

for (const name of ['WTSSendMessageW', 'MessageBoxW']) {
  const address = Module.findGlobalExportByName(name);
  if (address !== null) {
    Interceptor.replace(address, new NativeCallback(function () { return 1; }, 'bool',
      name === 'WTSSendMessageW'
        ? ['pointer', 'uint', 'pointer', 'uint', 'pointer', 'uint', 'uint', 'uint', 'pointer', 'bool']
        : ['pointer', 'pointer', 'pointer', 'uint']));
  }
}
"""


def extract_final_pe() -> bytes:
    with pyzipper.AESZipFile(ARCHIVE) as archive:
        archive.setpassword(b"infected")
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"expected one challenge binary, found {len(names)}")
        outer = archive.read(names[0])

    marker = outer.find(PAYLOAD_MARKER)
    if marker < 0:
        raise ValueError("payload marker not found")
    length_offset = marker + len(PAYLOAD_MARKER)
    payload_length = struct.unpack_from("<I", outer, length_offset)[0]
    scrambled = outer[length_offset + 4:length_offset + 4 + payload_length]
    if len(scrambled) != payload_length:
        raise ValueError("truncated scrambled PE payload")
    decoded = bytes(value ^ XOR_KEY[index % len(XOR_KEY)] for index, value in enumerate(scrambled))[::-1]
    if not decoded.startswith(b"MZ"):
        raise ValueError("decoded payload is not a PE file")
    return decoded


def extract_runtime_elf(executable: Path) -> bytes:
    result: dict[str, object] = {}
    complete = threading.Event()
    runtime_paths = [Path(tempfile.gettempdir()) / name for name in RUNTIME_FILES]
    for path in runtime_paths:
        if path.exists():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != RUNTIME_FILES[path.name]:
                raise FileExistsError(f"refusing to overwrite unrelated temporary file: {path}")
            path.unlink()
    device = frida.get_local_device()
    pid = device.spawn([str(executable)])
    session = device.attach(pid)

    def on_message(message: dict, data: bytes | None) -> None:
        payload = message.get("payload", {})
        if message.get("type") == "send" and payload.get("event") == "hidden-elf" and data is not None:
            result["blob"] = bytes(data)
            complete.set()
        elif message.get("type") == "send" and payload.get("event") == "error":
            result["error"] = payload.get("message", "unknown Frida error")
            complete.set()
        elif message.get("type") == "error":
            result["error"] = message.get("description", "Frida script error")
            complete.set()

    script = session.create_script(FRIDA_SOURCE)
    script.on("message", on_message)
    script.load()
    device.resume(pid)
    try:
        if not complete.wait(20):
            raise TimeoutError("timed out waiting for the unpacked ELF resource")
    finally:
        try:
            device.kill(pid)
        except frida.ProcessNotFoundError:
            pass
        session.detach()
        for path in runtime_paths:
            if path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != RUNTIME_FILES[path.name]:
                    raise ValueError(f"unexpected temporary artifact content: {path}")
                path.unlink()

    if "error" in result:
        raise RuntimeError(str(result["error"]))
    blob = result.get("blob")
    if not isinstance(blob, bytes) or not blob.startswith(b"\x7fELF"):
        raise ValueError("runtime resource is not an ELF file")
    return blob


def elf_section(blob: bytes, wanted: bytes) -> bytes:
    if blob[:4] != b"\x7fELF" or blob[4:6] != b"\x02\x01":
        raise ValueError("expected a little-endian ELF64 file")
    section_offset = struct.unpack_from("<Q", blob, 0x28)[0]
    section_size, section_count, names_index = struct.unpack_from("<HHH", blob, 0x3A)
    names_header = section_offset + names_index * section_size
    names_offset, names_size = struct.unpack_from("<QQ", blob, names_header + 0x18)
    names = blob[names_offset:names_offset + names_size]
    for index in range(section_count):
        header = section_offset + index * section_size
        name_offset = struct.unpack_from("<I", blob, header)[0]
        end = names.index(0, name_offset)
        name = names[name_offset:end]
        if name == wanted:
            offset, size = struct.unpack_from("<QQ", blob, header + 0x18)
            return blob[offset:offset + size]
    raise ValueError(f"ELF section {wanted!r} not found")


def recover_flag(blob: bytes) -> bytes:
    rodata = elf_section(blob, b".rodata")
    ciphertext = elf_section(blob, b".data")
    key = rodata[:16]
    if key != b"M68K_AES_FLAGKEY" or len(ciphertext) % AES.block_size:
        raise ValueError("unexpected AES material in hidden ELF")
    plaintext = unpad(AES.new(key, AES.MODE_ECB).decrypt(ciphertext), AES.block_size)
    if not (plaintext.startswith(b"psctf{") and plaintext.endswith(b"}")):
        raise ValueError("decryption did not produce a valid flag")
    return plaintext


def main() -> int:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        final_pe = extract_final_pe()
        executable = OUTPUT / "final.exe"
        executable.write_bytes(final_pe)
        hidden_elf = extract_runtime_elf(executable)
        (OUTPUT / "hidden-elf").write_bytes(hidden_elf)
        flag = recover_flag(hidden_elf)
    except Exception as error:
        print(f"solve failed: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
