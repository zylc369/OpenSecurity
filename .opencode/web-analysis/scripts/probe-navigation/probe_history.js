// Verify: history.go(-N) replay after BFCache eviction -> Sec-Fetch-Site: none
const http = require("node:http");
const puppeteer = require("puppeteer-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9969;
const EXEC = process.env.CHROME_PATH;
const requests = [];

http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  const tag = `${u.pathname}${u.search || ""}`;
  requests.push({ tag, sfSite: req.headers["sec-fetch-site"], sfUser: req.headers["sec-fetch-user"] });
  console.log(`REQ ${tag} | Sec-Fetch-Site=${req.headers["sec-fetch-site"]} Dest=${req.headers["sec-fetch-dest"]} User=${req.headers["sec-fetch-user"]}`);

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
    res.writeHead(200, H);
    const ev = u.searchParams.get("ev");
    if (ev === null) {
      res.end(`<!doctype html><body>B<script>
        setTimeout(()=>{ location.href = "/b?ev=1"; }, 120);
      </scr` + `ipt></body>`);
    } else {
      const n = parseInt(ev);
      res.end(`<!doctype html><body>B-ev${n}<script>
        ${n < 8
          ? `setTimeout(()=>{ location.href = "/b?ev=${n + 1}"; }, 120);`
          : `setTimeout(()=>{ console.log("evict done; going back 9"); history.go(-9); }, 200);`}
      </scr` + `ipt></body>`);
    }
    return;
  }
  res.writeHead(404); res.end();
}).listen(PORT, async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: EXEC, args: ["--no-sandbox"] });
  console.log("Chrome version:", await browser.version());
  const p = await browser.newPage();
  p.on("console", (m) => console.log("[chrome]", m.text()));
  await p.goto(`http://localhost:${PORT}/a`, { waitUntil: "domcontentloaded" });
  await sleep(4000);
  console.log("---- requests in order ----");
  for (const r of requests) console.log(JSON.stringify(r));
  await browser.close(); process.exit(0);
});
