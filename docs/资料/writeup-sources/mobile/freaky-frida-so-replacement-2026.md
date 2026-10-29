---
来源: https://pentest.bi0s.in/blog/posts/pwnsec-ctf-freaky-frida/
类型: html
获取日期: 2026-06-30
---

Freaky Frida - Pwnsec CTF Writeup

 Contents   

Freaky Frida - Pwnsec CTF Writeup

## Challenge Info

|  |  |  |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Field Details|  |  |  |  |  |  | | --- | --- | --- | --- | --- | --- | | CTF Pwnsec CTF|  |  |  |  | | --- | --- | --- | --- | | Challenge Freaky Frida|  |  | | --- | --- | | Category Android / Reverse Engineering | | | | | | | |

## Description

```` |  |  |
| --- | --- |
| ``` 1 ```   ``` It started as just another night at the lab. You opened Android Studio, loaded an APK, and whispered those famous words: “Let’s hook something simple…” Frida purred in the terminal. Everything seemed fine — until it wasn’t. Your screen flickered. Logcat went wild. The app whispered back. “Nice try, human.” Suddenly, "console.log(flag)" returned nothing. MainActivity crashed like your hopes of passing OSCP on the first try. You tried again, but the app laughed — a distorted sound echoing through JNI hell. "You think you can control me?" it taunted. Frida was no longer your tool; it had become the master. The app morphed, adapting to your every move. To retrieve the flag, you must outsmart the app's new defenses. Can you break free from Frida's grip and reclaim control? Note: they told me to use a Frida version lower than 17, and I totally agree with that advice, you should too. - @TK ``` | | ````

## Solution

From the description it is very evident that the APK has some anti Frida/anti tampering/ anti emulator checks, the APK crashes immediately when we try to open it We can proceed to inspect it in Jadx,

[![alt text](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-1.png)](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-1.png)

We see that the APK has two native libs

1. libFreakyFrida.so- libnative-lib.so

We can use Frida to understand which library is running the check and causes the crash

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 ```   ``` signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0xfa9358ed     rax 00000000a10f3c05  rbx 0000000000000001  rcx 00000000000067c8  rdx 00000000fa9358ed     r8  000070442afe1600  r9  0000000000000000  r10 0000000000000000  r11 00000000ffffffff     r12 000070442aa45dfe  r13 000070442aa45d00  r14 0000000000000001  r15 000070471920c500     rdi 000070442aa45990  rsi 0000000000019f20     rbp 000070442aa45cb0  rsp 000070442aa45990  rip 000070442ae3da65 backtrace:       #00 pc 0000000000175a65  /data/app/~~zgHg35F2pI9X469v-1CFHA==/com.pwnsec-xV14Nzi2wKH2vjZTbeTVXw==/base.apk!libnative-lib.so (offset 0x400000) (BuildId: ac659062ebd45e4c76cd79064d11bf80f6d2bdd8) *** [Remote::com.pwnsec ]-> ``` | | ````

`data/app/~~zgHg35F2pI9X469v-1CFHA==/com.pwnsec-xV14Nzi2wKH2vjZTbeTVXw==/base.APK!libnative-lib.so` tells us that `libnative-lib.so` is running the check and causing the crash, we can inspect the native library in Ghidra

[![alt text](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-2.png)](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-2.png)

This native lib is highly obfuscated and the strings are encrypted, it is pretty much difficult to understand what this native library is detecting, which crashes the APK I tried many bypass script - anti Frida,anti emulation,root checks but still the APK kept crashing From these two blogs [Blog 1](https://proandroiddev.com/bypassing-rasp-and-white-box-protections-24e677ad17ef) [Blog 2](https://tinyhack.com/2024/11/18/patching-so-files-of-an-installed-android-app/) I got a Technique where we replace the `.so` file of APK with a `.so` file which does nothing and only contains the boiler plate code of a `JNI_Onload` so that the APK works fine These are the steps to do that

1. Create a `stub.c` with the boiler plate code of `JNI_Onload` \

-> `nano stub.c`

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 ```   ```  __attribute__((visibility("default")))  int JNI_OnLoad(void *vm, void *reserved) {     return 0x00010006;  } ``` | | ````

1. Compile our `stub.c` to `libnative-lib.c` \

-> `gcc -shared -fPIC -nostdlib -o libnative-lib.so stub.c`

1. Decompile our original APK \

-> `apktool d FreakyFrida.APK`

1. Replace the original native lib with the file we made \

-> `cp libnative-lib.so FreakyFrida/lib/x86_64/libnative-lib.so`

1. Build the APK \

-> `apktool b FreakyFrida`

1. Sign the APK and install it \

-> `java -jar uber-APK-signer-1.3.0.jar -a FreakyFrida.APK` -> `ADB uninstall com.pwnsec` -> `ADB install FreakyFrida.ap` Now we can try to open the app in our emulator

[![alt text](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-3.png)](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-3.png)

We have successfully replaced the native lib which causes the crash, now we can focus on getting the flag For that, we need to inspect `libFreakyFrid.so` in Ghidra

[![alt text](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-4.png)](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-4.png)

[![alt text](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-5.png)](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-5.png)

In the launcher activity, there is method `CheckAsYouLike(str)` which takes our input and then calls another native method `strinfromJNI(str)` From Ghidra, we understood that we input is being compared with the flag and the some strings are being logged according to the result of `strcmp` So, we can write a Frida script to call the `CheckAsYouLike(str)` from Java and then hook the `strcmp` and log the arguments.

> P.S: Since, the instance of launcher activity is already created the `CheckAsYouLike(str)` is outside `OnCreate`, we need to use `Java.choose`

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 ```   ``` const f = Module.findExportByName("libc.so", "strcmp"); Interceptor.attach(f, {     onEnter(args) {             var s1 = Memory.readUtf8String(args[0]);             var s2 = Memory.readUtf8String(args[1]);             if(s1 == 'bruh'){                 console.log(s2)             }      } }); Java.perform(() => {     Java.choose("com.pwnsec.FreakyFrid", {         onMatch: function(instance) {             instance.stringFromJNI("bruh");         },         onComplete: function() {}     }); }); ``` | | ````

Now, we just need to load this script,

[![alt text](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-6.png)](/blog/assets/img/posts/pwnsec-ctf-freaky-frida/image-6.png)

## Flag

```` |  |  |
| --- | --- |
| ``` 1 ```   ``` FLAG:flag{Sup3r_$3cR3T_M0nK3y_FR3aKY_Fl@G_W17h_b@n@n@s_4ll_0v3r_7h3_P14n37} ``` | | ````

[Writeups](/blog/categories/writeups/), [CTF](/blog/categories/ctf/), [Mobile Security](/blog/categories/mobile-security/)

[ctf](/blog/tags/ctf/) [android](/blog/tags/android/) [reverse engineering](/blog/tags/reverse-engineering/) [mobile security](/blog/tags/mobile-security/)

This post is licensed under  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)  by the author.

Share