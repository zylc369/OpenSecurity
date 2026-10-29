// Self-navigation + pagehide post: is the message delivered when the SENDER triggers its own navigation?
const http = require("node:http");
const puppeteer = require("puppeteer-core");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9971;
const CSP = "sandbox allow-scripts; default-src 'none'; script-src 'nonce-tn'; frame-ancestors 'self'";
const EXEC = process.env.CHROME_PATH;

http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");

  if (u.pathname === "/host") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<!doctype html><body>HOST
      <iframe id="viewer" sandbox="allow-scripts" src="/sbx"></iframe>
      <script>
        addEventListener("message", (e) => {
          console.log("PARENT GOT data=" + JSON.stringify(e.data)
            + " | source===null: " + (e.source === null)
            + " | toString: " + Object.prototype.toString.call(e.source));
        });
      </scr` + `ipt></body>`);
    return;
  }

  if (u.pathname === "/sbx") {
    if (u.searchParams.has("done")) {
      setTimeout(() => {
        res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
        res.end("<!doctype html>DONE");
      }, 300);
      return;
    }
    res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": CSP });
    res.end(`<!doctype html><body><script nonce="tn">
      console.log("[S2] alive (self-nav + pagehide test)");
      addEventListener("pagehide", function () {
        console.log("[S2] pagehide fired (self-nav); posting now");
        top.postMessage({ m: "selfnav-pagehide" }, "*");
      });
      setTimeout(function () {
        console.log("[S2] self-navigating now");
        location.href = location.pathname + "?done";
      }, 500);
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
