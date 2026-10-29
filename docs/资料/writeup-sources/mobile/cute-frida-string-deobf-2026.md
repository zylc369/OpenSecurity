---
来源: https://pentest.bi0s.in/blog/posts/pwnsec-ctf-cute-frida/
类型: html
获取日期: 2026-06-30
---

Cute Frida - Pwnsec CTF Writeup

 Contents   

Cute Frida - Pwnsec CTF Writeup

## Challenge Info

|  |  |  |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Field Details|  |  |  |  |  |  | | --- | --- | --- | --- | --- | --- | | CTF Pwnsec CTF|  |  |  |  | | --- | --- | --- | --- | | Challenge Cute Frida|  |  | | --- | --- | | Category Android / Reverse Engineering | | | | | | | |

## Description

> This app is so cute yet so susy, isn’t it?

## Solution

We can start by inspecting it in Frida, the APK itself is pretty useless

[![alt text](/blog/assets/img/posts/pwnsec-ctf-cute-frida/image-1.png)](/blog/assets/img/posts/pwnsec-ctf-cute-frida/image-1.png)

In the Main Activity, we can see a sus string `What_do_you_mean_by_encrypted_flag` which has a value returned by `Deobfuscator$app$Release.getString(-548601664941L)` So we can try to hook the `Deobfuscator$app$Release.getString()` and log its output In the MainActivity, that method is called 5 times with different long values So, we need to log all those 5 outputs:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 ```   ``` Java.perform(function() {     var f =Java.use("com.joom.paranoid.Deobfuscator$app$Release");     var longs =[-548601664941, -3140818349, -28910622125, -308083496365, -338148267437];     for (var i = 0; i < longs.length; i++) {         var result = f.getString(longs[i]);         console.log(result);     } }); ``` | | ````

[![alt text](/blog/assets/img/posts/pwnsec-ctf-cute-frida/image-2.png)](/blog/assets/img/posts/pwnsec-ctf-cute-frida/image-2.png)

## Flag

```` |  |  |
| --- | --- |
| ``` 1 ```   ``` flag{7he_developer_is_S0_p4r4n01d_1t_th1nk5_Fr1d4_1s_3v3rywh3r3} ``` | | ````

[Writeups](/blog/categories/writeups/), [CTF](/blog/categories/ctf/), [Mobile Security](/blog/categories/mobile-security/)

[ctf](/blog/tags/ctf/) [android](/blog/tags/android/) [reverse engineering](/blog/tags/reverse-engineering/) [mobile security](/blog/tags/mobile-security/)

This post is licensed under  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)  by the author.

Share