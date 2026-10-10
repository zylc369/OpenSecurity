"""relayd CLI 入口。

用法:
  python -m services.remote_relayd genkey                 # 生成 PSK（base64 32B）
  python -m services.remote_relayd serve                  # 前台运行（PSK 经 env）
      REMOTE_RELAY_PSK=<base64> python -m services.remote_relayd serve
      可选: REMOTE_RELAY_PORT=41000 / REMOTE_RELAY_HOST=0.0.0.0
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
import secrets
from typing import cast

logger = logging.getLogger(__name__)

from services.remote_crypto import PSK_LEN
from services.remote_relayd.server import RelayServer


def genkey() -> str:
    """生成 PSK: base64(32B 随机)。"""
    return base64.b64encode(secrets.token_bytes(PSK_LEN)).decode()


def load_psk_from_env() -> bytes:
    raw = os.environ.get("REMOTE_RELAY_PSK", "")
    if not raw:
        raise SystemExit("缺少 REMOTE_RELAY_PSK（python -m services.remote_relayd genkey 生成）")
    import binascii
    try:
        psk = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as e:
        raise SystemExit(f"REMOTE_RELAY_PSK 不是合法 base64: {e}") from e
    if len(psk) != PSK_LEN:
        raise SystemExit(f"REMOTE_RELAY_PSK 必须为 {PSK_LEN} 字节的 base64")
    return psk


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remote-relayd", description=__doc__)
    parser.add_argument("command", choices=["serve", "genkey"])
    parser.add_argument("--host", default=os.environ.get("REMOTE_RELAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("REMOTE_RELAY_PORT", "41000")))
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: "list[str] | None" = None) -> None:
    ns = build_parser().parse_args(argv)
    command = cast("str", getattr(ns, "command", ""))
    verbose = cast("bool", getattr(ns, "verbose", False))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if command == "genkey":
        print(genkey())
        return
    psk = load_psk_from_env()
    server = RelayServer(psk)
    host = cast("str", getattr(ns, "host", "0.0.0.0"))
    port = cast("int", getattr(ns, "port", 41000))

    async def run() -> None:
        tcp_port = await server.serve(host, port)
        logger.info("relayd serving tcp+udp %s:%s", host, tcp_port)
        await asyncio.Event().wait()  # run forever

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
