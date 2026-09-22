// Force the parent to process the queued message AFTER the sender's document is gone.
// Parent busy-blocks the event loop across the sender's self-navigation commit.
const http = require("node:http");
const puppeteer = require("puppeteer-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9972;
const CSP = "sandbox allow-scripts; default-src 'none'; script-src 'nonce-tn'; frame-ancestors 'self'";
const EXEC = process.env.CHROME_PATH;

http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");

  if (u.pathname === "/host") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<!doctype html><body>HOST
      <iframe id="viewer" sandbox="allow-scripts" src="/sbx"></iframe>
      <script>
        const t0 = Date.now();
        addEventListener("message", (e) => {
          console.log("PARENT[" + (Date.now()-t0) + "ms] GOT data=" + JSON.stringify(e.data)
            + " | source===null: " + (e.source === null)
            + " | toString: " + Object.prototype.toString.call(e.source));
        });
        // busy-block the parent event loop from 300ms to 1800ms
        setTimeout(() => {
          console.log("PARENT[" + (Date.now()-t0) + "ms] busy start");
          const end = Date.now() + 1500;
          while (Date.now() < end) {}
          console.log("PARENT[" + (Date.now()-t0) + "ms] busy end");
        }, 300);
      </scr` + `ipt></body>`);
    return;
  }

  if (u.pathname === "/sbx") {
    if (u.searchParams.has("done")) {
      // delay the new document so its commit lands inside the parent's busy window
      setTimeout(() => {
        res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
        res.end("<!doctype html>DONE");
      }, 400);
      return;
    }
    res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
    res.end(`<!doctype html><body><script nonce="tn">
      const t0 = Date.now();
      setTimeout(function () {
        console.log("[S2][" + (Date.now()-t0) + "ms] posting then self-navigating");
        top.postMessage({ m: "selfnav" }, "*");
        location.href = location.pathname + "?done";
      }, 150);
    </scr` + `ipt></body>`);
    return;
  }
  res.writeHead(404); res.end();
}).listen(PORT, async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: EXEC, args: ["--no-sandbox"] });
  console.log("Chrome version:", await browser.version());
  const p = await browser.newPage();
  p.on("console", (m) => console.log("[chrome]", m.text()));
  await p.goto(`http://localhost:${PORT}/host`, { waitUntil: "domcontentloaded" });
  await sleep(3500);
  await browser.close(); process.exit(0);
});
