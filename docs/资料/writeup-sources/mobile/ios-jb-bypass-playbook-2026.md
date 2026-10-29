---
来源: https://nirajkharel.com.np/posts/ios-jailbreak-detection-bypass/
类型: html
获取日期: 2026-06-30
---

iOS - Jailbreak Detection Bypass | Niraj Kharel 

[![avatar](https://avatars.githubusercontent.com/u/47778874?v=4)](/)

[Niraj Kharel](/)

Find My Offensive Security Blogs

* [HOME](/) * [CATEGORIES](/categories/) * [TAGS](/tags/) * [ARCHIVES](/archives/) * [ABOUT](/about/)

[Home](/)   iOS - Jailbreak Detection Bypass  

Post

     Cancel

# iOS - Jailbreak Detection Bypass

Posted  *Jul 7, 2026*  

By  *[Niraj Kharel](https://github.com/nirajkharel)*  

*6 min* read

iOS jailbreak detection clusters into three vectors. Knowing each one and the matching bypass lets you survive on a JB device through any app that runs JB checks. This post is a working playbook.

**Vulnerable demo** · [VulnLabAppiOS](https://github.com/nirajkharel/VulnLabAppiOS)

* `ios/VulnLabAppiOS/Detection/DetectionViewController.swift` (`checkJailbreakFilesystem`, `checkJailbreakURLSchemes`, `checkJailbreakDyldImages`)

**The three vectors, VulnLabAppiOS’s implementation**

**1. File-existence checks.** VulnLabAppiOS’s `checkJailbreakFilesystem`:

[![DetectionViewController.swift checkJailbreakFilesystem (highlight 1) and checkJailbreakURLSchemes canOpenURL (highlight 2)]()](https://raw.githubusercontent.com/nirajkharel/nirajkharel.github.io/master/assets/img/images/ios-jailbreak-annotated.png)

**Highlight 1** is `if FileManager.default.fileExists(atPath: path) { return true }` - path existence check routed through `NSFileManager`; Frida hooks `-[NSFileManager fileExistsAtPath:]` to always return `false`, bypassing the entire path list in one hook.

**Highlight 2** is `if UIApplication.shared.canOpenURL(url) { return true }` - URL scheme reachability check routed through `UIApplication`; Frida hooks `-[UIApplication canOpenURL:]` to return `false` for any jailbreak scheme, silencing this check independently.

**2. URL scheme checks.** VulnLabAppiOS’s `checkJailbreakURLSchemes`:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 ```   ``` private func checkJailbreakURLSchemes() -> Bool {     let schemes = ["cydia://", "sileo://", "zbra://", "filza://"]     for scheme in schemes {         if let url = URL(string: scheme),            UIApplication.shared.canOpenURL(url) { return true }     }     return false } ``` | | ````

**3. dyld image scan.** VulnLabAppiOS’s `checkJailbreakDyldImages`:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 ```   ``` private func checkJailbreakDyldImages() -> Bool {     let count = _dyld_image_count()     for i in 0..<count {         if let name = _dyld_get_image_name(i) {             let s = String(cString: name)             if s.contains("MobileSubstrate") || s.contains("TweakInject") { return true }         }     }     return false } ``` | | ````

Plus more obscure libc-level checks seen in the wild:

* `stat` / `access` / `fopen` on the same paths (bypassable at a lower layer).* `fork()` returning a valid PID on jailbroken devices.* Reading `/etc/passwd` and noting non-default entries.

**The bypass, hooking the underlying OS functions**

VulnLabAppiOS’s check methods are declared `private` in Swift — no `@objc` thunk, unreachable by ObjC selector. Hook the OS functions they call instead. This also works on real-world apps where JB-check selectors are stripped or obfuscated.

For NSFileManager:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 ```   ``` const NSFM = ObjC.classes.NSFileManager; const blockedPaths = [     '/Applications/Cydia.app',     '/Applications/Sileo.app',     '/Applications/Zebra.app',     '/Applications/Filza.app',     '/private/var/lib/apt/',     '/private/var/lib/cydia/',     '/usr/bin/ssh',     '/bin/bash',     '/etc/apt/',     '/var/lib/undecimus/',     '/usr/share/jailbreak/' ]; const origExists = NSFM['- fileExistsAtPath:'].implementation; Interceptor.attach(origExists, {     onEnter: function (args) {         const path = new ObjC.Object(args[2]).toString();         for (const b of blockedPaths) {             if (path.indexOf(b) === 0) {                 this.block = true;                 break;             }         }     },     onLeave: function (retval) {         if (this.block) retval.replace(0);   // false     } }); ``` | | ````

For UIApplication canOpenURL:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 ```   ``` const UIApp = ObjC.classes.UIApplication; const blockedSchemes = ['cydia', 'sileo', 'zbra', 'filza', 'undecimus']; Interceptor.attach(UIApp['- canOpenURL:'].implementation, {     onEnter: function (args) {         const url = new ObjC.Object(args[2]).toString();         for (const s of blockedSchemes) {             if (url.indexOf(s + '://') === 0) {                 this.block = true;                 break;             }         }     },     onLeave: function (retval) {         if (this.block) retval.replace(0);     } }); ``` | | ````

After these two hooks, VulnLabAppiOS’s JB checks return “clean”. Apps that bypass NSFileManager and call `stat`/`access`/`fopen` directly at the libc layer need an additional hook per symbol — find the export in the specific system library (`libsystem_kernel.dylib`) and attach the same path-filter logic.

**The fork() and getppid() checks**

Some apps check `fork()`:

```` |  |  |
| --- | --- |
| ``` 1 ```   ``` if (fork() >= 0) return YES; ``` | | ````

`fork` returns -1 on a non-JB device (the sandbox forbids it). On JB devices the sandbox is loosened and `fork` returns a valid PID. Bypass:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 ```   ``` const kernLib = Process.findModuleByName('libsystem_kernel.dylib'); const fork = kernLib && kernLib.findExportByName('fork'); if (fork) Interceptor.attach(fork, {     onLeave: function (retval) {         retval.replace(-1);   // pretend fork failed     } }); ``` | | ````

Or check `getppid()`:

```` |  |  |
| --- | --- |
| ``` 1 ```   ``` if (getppid() != 1) return YES; ``` | | ````

The expected parent PID is 1 (launchd). On JB devices it might be different. Bypass:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 ```   ``` const kernLib = Process.findModuleByName('libsystem_kernel.dylib'); const getppid = kernLib && kernLib.findExportByName('getppid'); if (getppid) Interceptor.attach(getppid, {     onLeave: function (retval) {         retval.replace(1);     } }); ``` | | ````

**The dyld and module-name checks**

Apps that check the loaded module list for JB-specific tweaks:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 ```   ``` uint32_t count = _dyld_image_count(); for (uint32_t i = 0; i < count; i++) {     const char *name = _dyld_get_image_name(i);     if (strstr(name, "MobileSubstrate") || strstr(name, "TweakInject")) return YES; } ``` | | ````

Bypass:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 ```   ``` const dyldLib = Process.findModuleByName('libdyld.dylib'); const dyld = dyldLib && dyldLib.findExportByName('_dyld_get_image_name'); if (dyld) Interceptor.attach(dyld, {     onLeave: function (retval) {         const name = retval.readCString();         if (name && /Substrate|TweakInject|frida|libtweakinject/.test(name)) {             retval.replace(Memory.allocUtf8String('libSystem.B.dylib'));         }     } }); ``` | | ````

This rewrites the returned module name to a benign name. The detection sees only legitimate libraries.

**The combined drop-in script**

The hooks above stitch into a single file. Save as `ios-jb-bypass.js`:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 ```   ``` // frida -U -f com.vulnlab.iosapp --no-pause -l ios-jb-bypass.js setTimeout(function () {     const blockedPaths = [         '/Applications/Cydia.app', '/Applications/Sileo.app',         '/Applications/Zebra.app', '/Applications/Filza.app',         '/private/var/lib/apt/', '/private/var/lib/cydia/',         '/usr/bin/ssh', '/usr/libexec/sshd', '/bin/bash',         '/etc/apt/', '/var/lib/undecimus/', '/usr/share/jailbreak/'     ];     const blockedSchemes = ['cydia', 'sileo', 'zbra', 'filza', 'undecimus'];      // NSFileManager.fileExistsAtPath     const NSFM = ObjC.classes.NSFileManager;     Interceptor.attach(NSFM['- fileExistsAtPath:'].implementation, {         onEnter: function (args) {             const p = new ObjC.Object(args[2]).toString();             for (const b of blockedPaths) if (p.indexOf(b) === 0) { this.block = true; break; }         },         onLeave: function (retval) { if (this.block) retval.replace(0); }     });      // UIApplication.canOpenURL     const UIApp = ObjC.classes.UIApplication;     Interceptor.attach(UIApp['- canOpenURL:'].implementation, {         onEnter: function (args) {             const u = new ObjC.Object(args[2]).toString();             for (const s of blockedSchemes) if (u.indexOf(s + '://') === 0) { this.block = true; break; }         },         onLeave: function (retval) { if (this.block) retval.replace(0); }     });      // fork / getppid spoof     const kernLib = Process.findModuleByName('libsystem_kernel.dylib');     if (kernLib) {         const fork = kernLib.findExportByName('fork');         if (fork) Interceptor.attach(fork, { onLeave: function (retval) { retval.replace(-1); } });         const getppid = kernLib.findExportByName('getppid');         if (getppid) Interceptor.attach(getppid, { onLeave: function (retval) { retval.replace(1); } });     }      // dyld module name rewrite     const dyldLib = Process.findModuleByName('libdyld.dylib');     if (dyldLib) {         const dyld = dyldLib.findExportByName('_dyld_get_image_name');         if (dyld) Interceptor.attach(dyld, {             onLeave: function (retval) {                 const name = retval.readCString();                 if (name && /Substrate|TweakInject|frida|libtweakinject/.test(name)) {                     retval.replace(Memory.allocUtf8String('libSystem.B.dylib'));                 }             }         });     }      console.log('[*] jailbreak bypass hooks armed'); }, 2000); ``` | | ````

Two ObjC hooks cover file-existence checks and URL scheme checks. The fork/getppid/dyld hooks cover the lower-layer signals. Most JB detection ceases firing after this.

[![DetectionViewController.swift checkJailbreakFilesystem (highlight 1) and checkJailbreakURLSchemes canOpenURL (highlight 2)]()](https://raw.githubusercontent.com/nirajkharel/nirajkharel.github.io/master/assets/img/images/ios-jailbreak-1.png)

The remaining 5-10% of apps use behavioral / native-side checks (binary checksums, periodic re-scans, attestation-based detection) that need per-app analysis on top of this baseline.

**The integrity-check variant**

Modern banking apps add checksum-based checks on the app’s own binary or on critical libraries:

```` |  |  |
| --- | --- |
| ``` 1 2 3 4 ```   ``` // Compute SHA-256 of __TEXT segment uint8_t hash[32]; sha256_compute_segment(get_text_segment(), hash); if (memcmp(hash, EXPECTED_HASH, 32) != 0) return YES;   // tampered ``` | | ````

These do not depend on file-existence or syscalls. They are bypassed by:

* Patching the comparison logic out of the binary (find the `memcmp` call, replace with always-equal).* Restoring the original bytes before each verification window.

Significantly more work than the standard JB-detection bypass. Worth recognizing when you see it (“the app keeps crashing after I attach Frida, even though my JB-detection bypass is active”).

**Closing**

iOS jailbreak detection is the iOS analogue of Android root detection. The vectors are well-known. The drop-in script above plus the methodology of hooking-then-watching-trace covers the bulk of apps. For apps with binary-integrity checks, the bypass moves to inline patching.

Happy Hacking !!

[Mobile Pentesting](/categories/mobile-pentesting/), [iOS](/categories/ios/)

[Mobile Pentesting](/tags/mobile-pentesting/) [iOS](/tags/ios/) [Jailbreak Detection](/tags/jailbreak-detection/) [Frida](/tags/frida/)

This post is licensed under  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)  by the author.

Share

Trending Tags

[Mobile Pentesting](/tags/mobile-pentesting/) [iOS](/tags/ios/) [Android](/tags/android/) [Red Teaming](/tags/red-teaming/) [Offensive Programming](/tags/offensive-programming/) [HackTheBox](/tags/hackthebox/) [HTB](/tags/htb/) [Android Pentesting](/tags/android-pentesting/) [Data Disclosure](/tags/data-disclosure/) [File Disclosure](/tags/file-disclosure/)

### Further Reading

[*Jul 24, 2026* 

### iOS - Runtime Memory Scanning for Secrets

Static analysis finds secrets that are in the binary. It misses secrets that are assembled at runtime - a token decrypted from CoreData at launch, a JWT built from a stored key and a fresh timestam...](/posts/ios-memory-scan-secrets/)

[*Jul 27, 2026* 

### iOS - CCCrypt Live Interception

CCCrypt is the one-shot CommonCrypto function that the majority of iOS apps reach for when they want AES or DES. Static analysis tells you the algorithm constant. It does not tell you the runtime k...](/posts/ios-cccrypt-live-interception/)

[*Jul 18, 2026* 

### iOS - UIActivity Share Sheet Data Leak

UIActivityViewController is the iOS share sheet - the tray that lets users copy, AirDrop, save to Files, print, or send data to third-party apps. When the app presents the share sheet with sensitiv...](/posts/ios-uiactivity-share-sheet-leak/)

[iOS - Deep Link Parsing](/posts/ios-deeplink-parsing/) [iOS - Debugger Detection Bypass](/posts/ios-debugger-detection-bypass/)

Trending Tags

[Mobile Pentesting](/tags/mobile-pentesting/) [iOS](/tags/ios/) [Android](/tags/android/) [Red Teaming](/tags/red-teaming/) [Offensive Programming](/tags/offensive-programming/) [HackTheBox](/tags/hackthebox/) [HTB](/tags/htb/) [Android Pentesting](/tags/android-pentesting/) [Data Disclosure](/tags/data-disclosure/) [File Disclosure](/tags/file-disclosure/)

×

A new version of content is available.

 Update