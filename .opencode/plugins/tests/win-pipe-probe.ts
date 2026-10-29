/**
 * Windows 管道探测（CI 用，test_windows_ipc.py 子进程调用）。
 *
 * node:net.connect 连命名管道（Bun 1.1.28+ 官方支持路径）+ 手写 HTTP 报文
 * → GET /health → 200 则 exit 0。
 * 这是 controlFetch Windows 主路径的真机裁决点。若失败，CI 红——
 * controlFetch 将走 TCP 候选段回退（control-http.ts 已内置）。
 * 注意：不用 node:http 的 socketPath（Bun 在 Windows 管道上有未修复 bug
 * oven-sh/bun#18653）。
 */
import { connect } from "node:net";

const PIPE = "\\\\.\\pipe\\opensecurity-control-482964";

const socket = connect(PIPE);
const chunks: Buffer[] = [];
let exited = false;

const finish = (code: number, msg: string) => {
  if (exited) return;
  exited = true;
  socket.destroy();
  if (code === 0) console.log(msg);
  else console.error(msg);
  process.exit(code);
};

setTimeout(() => finish(1, "bun pipe probe: timeout"), 8000);

socket.on("connect", () => {
  socket.write("GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n");
});

socket.on("data", (c: Buffer) => chunks.push(c));

socket.on("end", () => {
  const raw = Buffer.concat(chunks).toString();
  const m = raw.match(/^HTTP\/\d\.\d (\d+)/);
  if (m && m[1] === "200" && raw.includes("ok")) {
    finish(0, `bun pipe probe: 200（node:net 管道路径可用）`);
  } else {
    finish(1, `bun pipe probe: 意外响应 ${raw.slice(0, 80)}`);
  }
});

socket.on("error", (e: Error) => finish(1, `bun pipe probe 失败: ${e.message}`));
