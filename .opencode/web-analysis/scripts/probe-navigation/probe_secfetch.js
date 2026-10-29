// Verify Sec-Fetch-* for: script navigation (location.href), reload, history.go()
const http = require("node:http");
const puppeteer = require("puppeteer-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9970;
const EXEC = process.env.CHROME_PATH;
const requests = [];

http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  const tag = `${u.pathname}${u.search || ""}`;
  requests.push({ tag, sfSite: req.headers["sec-fetch-site"], sfDest: req.headers["sec-fetch-dest"], sfUser: req.headers["sec-fetch-user"], sfMode: req.headers["sec-fetch-mode"] });
  console.log(`REQ ${tag} | Sec-Fetch-Site=${req.headers["sec-fetch-site"]} Dest=${req.headers["sec-fetch-dest"]} User=${req.headers["sec-fetch-user"]} Mode=${req.headers["sec-fetch-mode"]}`);

  const H = { "Content-Type": "text/html", "Cache-Control": "no-store" };

  if (u.pathname === "/a") {
    res.writeHead(200, H);
    res.end(`<!doctype html><body>A<script>
      if (!sessionStorage.getItem("wentB")) {
        sessionStorage.setItem("wentB","1");
        setTimeout(()=>{ location.href = "/b"; }, 400);
      } else {
        console.log("BACK AT /a (history replay), navtype=" + performance.getEntriesByType("navigation")[0].type);
      }
    </scr` + `ipt></body>`);
    return;
  }
  if (u.pathname === "/b") {
    const ev = u.searchParams.get("ev");
    res.writeHead(200, H);
    if (ev === null) {
      res.end(`<!doctype html><body>B<script>
        let n = 0;
        const t = setInterval(()=>{ n++; if (n<=8) { location.href = "/b?ev=" + n; } else { clearInterval(t); setTimeout(()=>{ history.go(-9); }, 200); } }, 120);
      </scr` + `ipt></body>`);
    } else {
      res.end(`<!doctype html><body>B-ev${ev}`);
    }
    return;
  }
  if (u.pathname === "/r") {
    res.writeHead(200, H);
    const navtype = u.searchParams.get("again");
    res.end(`<!doctype html><body>R<script>
      console.log("R navtype=" + performance.getEntriesByType("navigation")[0].type);
      if (!location.search.includes("again")) setTimeout(()=>{ location.reload(); }, 400);
    </scr` + `ipt></body>`);
    return;
  }
  res.writeHead(404); res.end();
}).listen(PORT, async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: EXEC, args: ["--no-sandbox"] });
  console.log("Chrome version:", await browser.version());
  const p = await browser.newPage();
  p.on("console", (m) => console.log("[chrome]", m.text()));

  console.log("---- TEST 1: location.href script navigation ----");
  await p.goto(`http://localhost:${PORT}/a`, { waitUntil: "domcontentloaded" });
  await sleep(1200); // /a -> /b happens; then eviction chain (8*120ms + settle)
  await sleep(2500); // wait for history.go(-9) and replay
  console.log("---- TEST 2: location.reload() ----");
  await p.goto(`http://localhost:${PORT}/r`, { waitUntil: "domcontentloaded" });
  await sleep(1200);
  await sleep(800);
  console.log("---- SUMMARY ----");
  for (const r of requests) console.log(JSON.stringify(r));
  await browser.close(); process.exit(0);
});
