// Probe: does `window.opener = null` in a popup revoke the parent reference that the
// popup can recover from `event.source` of a later postMessage?
//
// Assertion (matches the documented behavior):
//   msg1 (before opener=null): popup sees e.source !== null and can postMessage back via it.
//   msg2 (after popup sets window.opener = null): popup STILL sees e.source !== null and can
//   postMessage back -> e.source preserves the sender WindowProxy even after the receiving
//   side nulled its opener reference. `opener = null` breaks the *stored* reference, not the
//   per-message sender identity.
//
// Output: JSON {chrome, msg1SrcNotNull, pong1Received, openerIsNull, msg2SrcNotNull, pong2Received, recoveryWorks}
//   recoveryWorks === true -> nulling opener does NOT block e.source recovery (documented behavior confirmed)
//   recoveryWorks === false -> e.source became null after opener=null; knowledge must follow observation.
const http = require("node:http");
const puppeteer = require("puppeteer-core");

const PORT_A = 9983; // parent origin
const PORT_B = 9984; // popup origin (cross-origin to A: different port on 127.0.0.1)
const PONG_TIMEOUT = 5000;

const serverA = http.createServer((req, res) => {
  if (req.url.startsWith("/parent")) {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<!doctype html><body>PARENT<script>
      window.pongs = [];
      addEventListener('message', (e) => { if (e.data && e.data.pong) pongs.push(e.data.pong); });
      window.run = async () => {
        const pop = open('http://127.0.0.1:${PORT_B}/popup', 'pop', 'width=500,height=400');
        await new Promise(r => setTimeout(r, 800));
        pop.postMessage({msg: 1}, '*');
        await new Promise(r => setTimeout(r, 600));
        pop.postMessage({msg: 2}, '*');   // popup has nulled opener before this arrives? see popup script
        await new Promise(r => setTimeout(r, 800));
        return { pong1: pongs.includes(1), pong2: pongs.includes(2) };
      };
    </script></body>`);
    return;
  }
  res.writeHead(404); res.end();
});

const serverB = http.createServer((req, res) => {
  if (req.url.startsWith("/popup")) {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<!doctype html><body>POPUP<script>
      window.state = {};
      addEventListener('message', (e) => {
        const rec = { srcNotNull: e.source !== null && typeof e.source.postMessage === 'function' };
        if (e.data.msg === 1) {
          state.msg1SrcNotNull = rec.srcNotNull;
          if (rec.srcNotNull) { e.source.postMessage({pong: 1}, '*'); window.opener = null; }
          state.openerIsNull = window.opener === null;
        }
        if (e.data.msg === 2) {
          state.msg2SrcNotNull = rec.srcNotNull;
          if (rec.srcNotNull) e.source.postMessage({pong: 2}, '*');
          document.title = 'DONE:' + JSON.stringify(state);
        }
      });
    </script></body>`);
    return;
  }
  res.writeHead(404); res.end();
});

(async () => {
  const chrome = process.env.CHROME_PATH;
  serverA.listen(PORT_A); serverB.listen(PORT_B);
  const browser = await puppeteer.launch({
    executablePath: chrome,
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const pg = await browser.newPage();
    const popupTitle = await new Promise((resolve) => {
      // 兜底: popup 被拦截/goto 失败时按 PONG_TIMEOUT 超时，保证脚本输出 JSON 并以 exit 2 结束（不永久挂起）
      const timer = setTimeout(() => resolve("{}"), PONG_TIMEOUT);
      const settle = (v) => { clearTimeout(timer); resolve(v); };
      pg.on("popup", async (pop) => {
        for (let i = 0; i < 50; i++) {
          const t = await pop.title().catch(() => "");
          if (t.startsWith("DONE:")) return settle(t.slice(5));
          await new Promise((r) => setTimeout(r, 200));
        }
        settle("{}");
      });
      pg.goto(`http://127.0.0.1:${PORT_A}/parent`, { waitUntil: "domcontentloaded" })
        .then(() => pg.evaluate(() => window.run()))
        .catch(() => settle("{}"));
    });
    const pongs = await pg.evaluate(() => ({ pong1: window.pongs.includes(1), pong2: window.pongs.includes(2) }));
    const st = JSON.parse(popupTitle);
    const result = {
      chrome: chrome.split("/mac_arm-")[1]?.split("/")[0] || chrome,
      msg1SrcNotNull: st.msg1SrcNotNull === true,
      pong1Received: pongs.pong1 === true,
      openerIsNull: st.openerIsNull === true,
      msg2SrcNotNull: st.msg2SrcNotNull === true,
      pong2Received: pongs.pong2 === true,
    };
    result.recoveryWorks = result.msg1SrcNotNull && result.pong1Received && result.openerIsNull && result.msg2SrcNotNull && result.pong2Received;
    console.log(JSON.stringify(result));
    if (result.recoveryWorks !== true) process.exitCode = 2;
  } finally {
    await browser.close(); serverA.close(); serverB.close();
  }
})();
