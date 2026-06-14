# 分析-JS-Safe-6.0

## 文件位置

`examples/web/js_safe_6.html`

## 题目

You stumbled upon someone’s “JS Safe” on the web. It’s a simple HTML file that can store secrets
in the browser’s localStorage. This means that you won’t be able to extract any secret from it
(the secrets are on the computer of the owner), but it looks like it was hand-crafted to work only
with the password of the owner…

## 用法

Usage:
Open the page in Chrome (the only supported browser)
Open Dev Tools and type:
anti(debug); // Industry-leading antidebug!
unlock("password"); // -> alert(secret)
store("new secret");