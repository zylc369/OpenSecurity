from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

try:
    import frida
except ImportError as exc:
    raise SystemExit("missing dependency: python -m pip install frida==17.5.2") from exc


CHALLENGE_DIR = Path(__file__).resolve().parent
CHALLENGE_ARCHIVE = CHALLENGE_DIR / "challenge" / "dist (1).zip"
CHALLENGE_EXE = Path()
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_{}"
EXPECTED = base64.b64decode(
    "1YaflhhKM8DN9S6HdkAk5SylvH4NGIx5K8vPpd0sppuXHRAPMy4S2J6t33wkXDrj"
    "j3BpJNW5FgMTZjJ0j1jrQXxDhe9pplx4QgQ80tyaOD9rTM35m6cgHzJV31Dyavrh7"
    "4lqf65Rx0FnRJgOZXWD1CSN85YrOFmdP0h6QDoyowJEkMF/fTfKHhbjJtgxxw/8JZ"
    "akPfXTBMKxRaJeEd6a+a3Zxd1wogDOuujA539wloum5uqLiwmz2PmZL86VWxhr5kN"
    "rcuAkbAAzI8Y6K9dPJ92PFOAeR6X9nyMPxLyI17qRbPCpHb/Nh26EYqusiuruZbLB"
    "ebZUBSQp1l9tf8VuEZ/jfNHZ/WcwH0v6L2jaodCC6hXIny/8jxS2yg2O80HGawi3g"
    "e5MR+4Ds6ZK1TRpTd14hTOHy/dtzX3/gSM9lq0RKOW3qF0bA8Qi0jV3i1jrxSKg5Z"
    "Ha3WJA+an9gWIaj7NXQuNUiirXefW5jZuacmi2hB0JPTSPCLcq2NwpZ+fQi5935VK"
    "Q2t+VCYHjInHIuTERGYJnULx64S7dLVxa1IdwrEhTOqP/4Ffwd8X3TSnBdpYrgPEq"
    "MkPZBq6buWr2DwDVtvQtkUMEfAS1OO04RP4VbCPyILCKD5rKgXm55xCY2K8GARaMJ"
    "6lUHuOSX6p7S5zdMEDtf3y7a1/d6kRlwgGpXxKRlkfxaecHrGzCgadJkLovgIMleAU"
    "rFcA/hRMyS2RouDGGytVYorS1Zgin+OtZWJwpB+CA4KzDTkp0xeIlF7P32lR3GbKYn"
    "NJPg7UVEvNspVvYaXCh3juxIzJgyH0MUIDgBWjI2glWmPF/amDMZ1jYO4JRxlDX7Br"
    "gXtkjdejD5Le9b23dyb6+9tfjzJfntHRJ0A88qAXxk3O57wUqa+au/1QudS6WnLGE"
    "cloixWOKwR5gks8BFk5EZvUa6cgPJ8WlhTCIOb+/7QczHpwjFrnvp7Q3LodzOZr+xw"
    "KwsNK/CX2yt+w55VrIyHG+LtFsWJV9OBj2l+KmYeW3paQxBq5rriUyY/fD0KVPviT"
    "xn8Sy1jfjyl/VQm6IBGVG2jxzVWjVJ8RfbNsRTFzhE9EIkz2whrgoK1Yartu3L/pC"
    "AY9P0CXhIJitRTRrDVKKYrdbd2+Vng2f8fKJ+i01ihho/638mJG2pjIFUb+jHodZm8"
    "6qjPoO9qAZSw6fF2Z7t9RNNxfb6kfiloMJqUq7OIAANFqgOWLwOW7q7aHrnlN/LW/"
    "fjui89qbxZKZWCb4aRxQfflMKSQAhvUKYYQ2KHUCf"
)

TOKEN_RPC_SCRIPT = r"""
function api(name, ret, args) {
  return new NativeFunction(Module.getGlobalExportByName(name), ret, args);
}
const py = {
  ensure: api("PyGILState_Ensure", "int", []),
  release: api("PyGILState_Release", "void", ["int"]),
  addModule: api("PyImport_AddModule", "pointer", ["pointer"]),
  getAttr: api("PyObject_GetAttrString", "pointer", ["pointer", "pointer"]),
  setAttr: api("PyObject_SetAttrString", "int", ["pointer", "pointer", "pointer"]),
  listNew: api("PyList_New", "pointer", ["int64"]),
  listSet: api("PyList_SetItem", "int", ["pointer", "int64", "pointer"]),
  listSize: api("PyList_Size", "int64", ["pointer"]),
  listGet: api("PyList_GetItem", "pointer", ["pointer", "int64"]),
  bytesNew: api("PyBytes_FromStringAndSize", "pointer", ["pointer", "int64"]),
  bytesSize: api("PyBytes_Size", "int64", ["pointer"]),
  bytesData: api("PyBytes_AsString", "pointer", ["pointer"]),
  unicode: api("PyUnicode_FromString", "pointer", ["pointer"]),
  callOne: api("PyObject_CallOneArg", "pointer", ["pointer", "pointer"]),
  decref: api("Py_DecRef", "void", ["pointer"]),
  errPrint: api("PyErr_Print", "void", []),
  errClear: api("PyErr_Clear", "void", []),
  modules: api("PyImport_GetModuleDict", "pointer", []),
  dictGet: api("PyDict_GetItemString", "pointer", ["pointer", "pointer"]),
  isTrue: api("PyObject_IsTrue", "int", ["pointer"]),
};
function checked(value, label) {
  if (value.isNull()) {
    py.errPrint();
    throw new Error(label);
  }
  return value;
}
rpc.exports = {
  isready() {
    const state = py.ensure();
    try {
      const moduleObject = py.dictGet(
        py.modules(), Memory.allocUtf8String("enhanced"));
      if (moduleObject.isNull()) return false;
      const variable = py.getAttr(
        moduleObject, Memory.allocUtf8String("_0ab7e4d1"));
      if (variable.isNull()) {
        py.errClear();
        return false;
      }
      const ready = py.isTrue(variable) === 1;
      py.decref(variable);
      return ready;
    } finally {
      py.release(state);
    }
  },
  token(prefix, character, previousHex) {
    const state = py.ensure();
    try {
      const moduleObject = checked(
        py.addModule(Memory.allocUtf8String("enhanced")), "enhanced module");
      const tokenList = checked(py.listNew(previousHex.length), "token list");
      for (let index = 0; index < previousHex.length; index++) {
        const raw = previousHex[index].match(/../g).map(x => parseInt(x, 16));
        const buffer = Memory.alloc(raw.length);
        buffer.writeByteArray(raw);
        const token = checked(py.bytesNew(buffer, raw.length), "token bytes");
        if (py.listSet(tokenList, index, token) !== 0) throw new Error("list set");
      }
      if (py.setAttr(moduleObject, Memory.allocUtf8String("_6c1fa932"), tokenList) !== 0)
        throw new Error("set token list");
      py.decref(tokenList);

      const variable = checked(
        py.getAttr(moduleObject, Memory.allocUtf8String("_0ab7e4d1")), "StringVar");
      const setter = checked(py.getAttr(variable, Memory.allocUtf8String("set")), "set");
      const prefixObject = checked(
        py.unicode(Memory.allocUtf8String(prefix)), "prefix unicode");
      const setResult = checked(py.callOne(setter, prefixObject), "StringVar.set");
      py.decref(setResult);
      py.decref(prefixObject);
      py.decref(setter);
      py.decref(variable);

      const functionObject = checked(
        py.getAttr(moduleObject, Memory.allocUtf8String("_afa6b920")), "_afa6b920");
      const characterObject = checked(
        py.unicode(Memory.allocUtf8String(character)), "character unicode");
      const callResult = checked(py.callOne(functionObject, characterObject), "_afa6b920 call");
      py.decref(callResult);
      py.decref(characterObject);
      py.decref(functionObject);

      const outputList = checked(
        py.getAttr(moduleObject, Memory.allocUtf8String("_6c1fa932")), "output list");
      const outputSize = Number(py.listSize(outputList));
      const resultObject = checked(py.listGet(outputList, outputSize - 1), "result token");
      const resultSize = Number(py.bytesSize(resultObject));
      const resultData = py.bytesData(resultObject).readByteArray(resultSize);
      py.decref(outputList);
      return resultData;
    } finally {
      py.release(state);
    }
  }
};
"""

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_PIPE_BUSY = 231
ERROR_FILE_NOT_FOUND = 2

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.WaitNamedPipeW.restype = wintypes.BOOL
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]


def open_pipe(name: str) -> int:
    for _ in range(500):
        handle = kernel32.CreateFileW(
            name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
        )
        if handle != INVALID_HANDLE_VALUE:
            return handle
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            time.sleep(0.01)
        elif error == ERROR_PIPE_BUSY:
            kernel32.WaitNamedPipeW(name, 50)
        else:
            raise ctypes.WinError(error)
    raise TimeoutError(name)


def roundtrip(request: bytes) -> bytes:
    handle = open_pipe(r"\\.\pipe\upyxsvc")
    try:
        sent = wintypes.DWORD()
        source = ctypes.create_string_buffer(request)
        if not kernel32.WriteFile(handle, source, len(request), ctypes.byref(sent), None):
            raise ctypes.WinError(ctypes.get_last_error())
        result = ctypes.create_string_buffer(65536)
        received = wintypes.DWORD()
        if not kernel32.ReadFile(handle, result, len(result), ctypes.byref(received), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.raw[: received.value]
    finally:
        kernel32.CloseHandle(handle)


def service_transform(tokens: list[bytes]) -> tuple[bytes, bytes]:
    if roundtrip(b"\x10" + b"".join(tokens)) != b"\x01":
        raise RuntimeError("service rejected token vector")
    nonce = roundtrip(b"\x12")
    transformed = roundtrip(b"\x11")
    roundtrip(b"\x13")
    if len(nonce) != 32 or len(transformed) != 960:
        raise RuntimeError("unexpected service response length")
    return nonce, transformed


def launch_hidden() -> subprocess.Popen[bytes]:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return subprocess.Popen(
        [str(CHALLENGE_EXE)],
        cwd=CHALLENGE_DIR,
        startupinfo=startup,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def challenge_processes() -> list[object]:
    return [
        process
        for process in frida.get_local_device().enumerate_processes()
        if process.name.lower() == "challenge.exe"
    ]


def connect_token_rpc() -> tuple[object, object, int]:
    last_error: BaseException | None = None
    for _ in range(100):
        for process in sorted(challenge_processes(), key=lambda item: item.pid, reverse=True):
            session = None
            try:
                session = frida.attach(process.pid)
                script = session.create_script(TOKEN_RPC_SCRIPT)
                script.load()
                if not script.exports_sync.isready():
                    session.detach()
                    continue
                token = bytes(script.exports_sync.token("", "a", []))
                if len(token) == 16:
                    return session, script, process.pid
            except BaseException as exc:
                last_error = exc
                if session is not None:
                    session.detach()
        time.sleep(0.05)
    raise RuntimeError(f"could not attach to Python child: {last_error}")


def make_token(script: object, prefix: str, character: str, previous: list[bytes]) -> bytes:
    value = bytes(
        script.exports_sync.token(prefix, character, [token.hex() for token in previous])
    )
    if len(value) != 16:
        raise RuntimeError(f"invalid token length: {len(value)}")
    return value


def terminate_exact_process(process_id: int) -> None:
    handle = kernel32.OpenProcess(0x0001, False, process_id)
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 0)
    finally:
        kernel32.CloseHandle(handle)


def solve(script: object) -> str:
    baseline: list[bytes] = []
    for _ in range(60):
        baseline.append(make_token(script, "a" * len(baseline), "a", baseline))

    solved: list[str] = []
    solved_tokens: list[bytes] = []
    for position in range(58):
        matches: list[tuple[str, bytes]] = []
        for character in ALPHABET:
            token = make_token(script, "".join(solved), character, solved_tokens)
            trial = list(baseline)
            trial[:position] = solved_tokens
            trial[position] = token
            _, transformed = service_transform(trial)
            start = position * 16
            if transformed[start : start + 16] == EXPECTED[start : start + 16]:
                matches.append((character, token))
        if len(matches) != 1:
            raise RuntimeError(f"position {position}: expected one match, got {matches!r}")
        solved.append(matches[0][0])
        solved_tokens.append(matches[0][1])

    pair_matches: list[tuple[str, bytes, bytes]] = []
    prefix = "".join(solved)
    for first in ALPHABET:
        first_token = make_token(script, prefix, first, solved_tokens)
        second_token = make_token(
            script, prefix + first, "}", solved_tokens + [first_token]
        )
        nonce, _ = service_transform(solved_tokens + [first_token, second_token])
        if nonce == EXPECTED[-32:]:
            pair_matches.append((first + "}", first_token, second_token))
    if len(pair_matches) != 1:
        raise RuntimeError(f"final pair: expected one match, got {pair_matches!r}")
    solved.extend(pair_matches[0][0])
    flag = "".join(solved)
    if len(flag) != 60 or re.fullmatch(r"BHFlagY\{[A-Za-z0-9_]+\}", flag) is None:
        raise RuntimeError(f"invalid recovered flag: {flag!r}")
    return flag


def main() -> int:
    global CHALLENGE_EXE
    if sys.platform != "win32":
        raise SystemExit("this solver requires Windows")
    if not CHALLENGE_ARCHIVE.is_file():
        raise SystemExit(f"missing challenge file: {CHALLENGE_ARCHIVE}")

    output_dir = CHALLENGE_DIR / "output"
    output_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="upyx-", dir=output_dir) as temp_dir:
        CHALLENGE_EXE = Path(temp_dir) / "Challenge.exe"
        with zipfile.ZipFile(CHALLENGE_ARCHIVE) as archive:
            CHALLENGE_EXE.write_bytes(archive.read("Challenge.exe"))

        launched = None
        session = None
        attached_pid = None
        try:
            if challenge_processes():
                session, script, attached_pid = connect_token_rpc()
            else:
                launched = launch_hidden()
                time.sleep(2)
                session, script, attached_pid = connect_token_rpc()
            flag = solve(script)
            sys.stdout.buffer.write(flag.encode("ascii"))
            return 0
        finally:
            if session is not None:
                session.detach()
            if launched is not None:
                if attached_pid is not None:
                    terminate_exact_process(attached_pid)
                if launched.poll() is None:
                    launched.terminate()
                try:
                    launched.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    launched.kill()
                    launched.wait(timeout=5)
            for _ in range(20):
                try:
                    CHALLENGE_EXE.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.1)


if __name__ == "__main__":
    raise SystemExit(main())
