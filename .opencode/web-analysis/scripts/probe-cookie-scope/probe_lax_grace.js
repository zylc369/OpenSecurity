// Test: does Chrome's Lax+POST 2-minute grace apply to an EXPLICIT SameSite=Lax cookie?
// Setup: cookies set by 127.0.0.1:9000; form POST from a localhost:9000 page (cross-site) to 127.0.0.1:9000/receive
const http = require("node:http");
const puppeteer = require("puppeteer-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9011;
const EXEC = process.env.CHROME_PATH;

http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/login") {
    res.writeHead(200, {
      "Content-Type": "text/html",
      "Cache-Control": "no-store",
      "Set-Cookie": ["t=explicitLax; SameSite=Lax; Path=/", "u=unspecified; Path=/"],
    });
    res.end("<!doctype html>ok");
    return;
  }
  if (u.pathname === "/page") {
    res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
    res.end(`<!doctype html><body>PAGE<script>
      setTimeout(()=>{ document.getElementById("f").submit(); }, 300);
    </scr` + `ipt>
    <form id="f" action="http://127.0.0.1:${PORT}/receive" method="POST"><input name="x" value="1"></form></body>`);
    return;
  }
  if (u.pathname === "/receive") {
    console.log("RECEIVE(host=" + req.headers.host + ") Cookie header:", JSON.stringify(req.headers.cookie || ""));
    res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
    res.end("<!doctype html>received");
    return;
  }
  res.writeHead(404); res.end();
}).listen(PORT, async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: EXEC, args: ["--no-sandbox"] });
  console.log("Chrome version:", await browser.version());
  const p = await browser.newPage();
  await p.goto(`http://127.0.0.1:${PORT}/login`, { waitUntil: "domcontentloaded" });
  await sleep(300);
  const cookies = await p.cookies();
  console.log("cookies after login:", cookies.map((c) => `${c.name}=${c.value} (sameSite=${c.sameSite})`).join(" | "));
  await p.goto(`http://localhost:${PORT}/page`, { waitUntil: "domcontentloaded" });
  await sleep(1500);
  await browser.close(); process.exit(0);
});
