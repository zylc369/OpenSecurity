---
来源: https://zenn.dev/tera_p/articles/c2f6a85d510824
类型: html
获取日期: 2026-06-30
---

[![TeraP](https://static.zenn.studio/user-upload/avatar/2a29296d8a.jpeg)TeraP](/tera_p)

[![](https://static.zenn.studio/user-upload/topics/bb6b2477a6.jpeg)

Web](/topics/web)[![](https://zenn.dev/images/topic.png)

CTF](/topics/ctf)[![](https://zenn.dev/images/topic.png)

crypto](/topics/crypto)[![](https://zenn.dev/images/topic.png)

pwn](/topics/pwn)[![](https://zenn.dev/images/topic.png)

OSINT](/topics/osint)[![](https://static.zenn.studio/images/drawing/idea-icon.svg)

idea](/tech-or-idea)

## Introduction

Welcome to my first ever Zenn article. Me (TeraP) and my friends put together this writeup for BushBash CTF 2026. We won't be discussing every challenge due to the sheer number of them (only 9 out of 21 solved), but we hope you find the writeup informative and enjoyable. Cheers!

## Event Overview

* **Team:** Bao Bao
* **Player:** yuerei, xanderous, Zillaa, TeraP
* **Final Rank:** 59th place / 4090 points

## Solved Challenges (21)

| Category | Challenge | Score | Solves |
| --- | --- | --- | --- |
| Pwn | [hashing it out](#hashing-it-out) | 100 | 98 |
| Pwn | [cachebrowns](#cachebrowns) | 100 | 222 |
| Pwn | [Hack The Vault II](#hack-the-vault-ii) | 100 | 277 |
| Pwn | [mystery server II](#mystery-server-ii) | 433 | 79 |
| Crypto | [Beat Around The Bush](#beat-around-the-bush) | 200 | 219 |
| Crypto | [xored](#xored) | 200 | 333 |
| Crypto | [strawberries](#strawberries) | 219 | 182 |
| Web | [Secret hidden website](#secret-hidden-website) | 200 | 110 |
| Reverse | [password](#password) | 100 | 264 |
| Reverse | [⟨⟩⟨⟩](#%E2%9F%A8%E2%9F%A9%E2%9F%A8%E2%9F%A9) | 100 | 273 |
| Reverse | [Hack The Vault I](#hack-the-vault-i) | 100 | 387 |
| Reverse | [⟨⟩⟨⟩⟨⟩⟨⟩⟨⟩⟨⟩](#%E2%9F%A8%E2%9F%A9%E2%9F%A8%E2%9F%A9%E2%9F%A8%E2%9F%A9%E2%9F%A8%E2%9F%A9%E2%9F%A8%E2%9F%A9%E2%9F%A8%E2%9F%A9) | 155 | 222 |
| Reverse | [Turned Around](#turned-around) | 286 | 186 |
| Reverse | [mystery server I](#mystery-server-i) | 300 | 113 |
| OSINT | [The CSSA Hackerman I](#the-cssa-hackerman-i) | 100 | 347 |
| OSINT | [The CSSA Hackerman II](#the-cssa-hackerman-ii) | 100 | 194 |
| OSINT | [The CSSA Hackerman III](#the-cssa-hackerman-iii) | 397 | 33 |
| Misc | [Spiritual Interception](#spiritual-interception) | 100 | 317 |
| Misc | [Signal Haze](#signal-haze) | 200 | 163 |
| Misc | [matrix\_secrets](#matrix_secrets) | 300 | 72 |
| Misc | [chip](#chip) | 300 | 166 |

## Beat Around The Bush

Description

The flag is in the bush, can you find it? The flag format: is `bushbash{<words-separated-by-hyphens>}`

🌳🌲🌴🌵🎄🌿☘️🍀🍃🌴🍂🌵🍁🪴🌴🌵🌱🌴☘️🍂🌴🌾🌵🌳🌲🌴🌵🎋🎍🪴🌱🍂🌵🍁🪴🌴🌵🍂🎍☘️🍀🎍☘️🍀🪵🌵🌳🌲🌴🌵🍂🍃🌴🌴🪨🍃🌴🍂🍂🌵☘️🎍🍀🌲🌳🍂🌵🪴⛰️🍁🪴🌾 🍁☘️🌱🌵🌳🌲🌴🌵🍃⛰️🪴🎍🏕️🌴🌴🌳🍂🌵🍂🎍☘️🍀🪵🌵🎋🌿🍂🌲🎋🍁🍂🌲🌺🍂⛰️🌻🌼🍁☘️🌸🌻🌳🪴🌴🌴🍂🌻🍁☘️🌱🌻🏕️🍁☘️🍀🍁🪴⛰️⛰️🍂🪻🌵🎍☘️🌵🌳🌲🌴🌵🍃🍁☘️🌱 🌱⛰️🦌☘️🌵🌿☘️🌱🌴🪴🪵🌵🎄🌿🍂🌳🌵🌱⛰️☘️🦘🌳🌵🍀🌴🌳🌵🎋🎍🌳🌳🌴☘️🌵🎋🌸🌵🍁🌵🍂🪨🎍🌱🌴🪴🪵

**Author:** Harold Gao

Writeup

* **Solver:** TeraP

I recognized what this is immediately, so I can just start deciphering right away. The trick I used is to look for the most repeated emoji, I found that there are 26 instances of `🌵`, I'll rule them out to be a `space`. Next, 4 instances of `🌳🌲🌴` caged by `🌵` before and after, I'll just make them out to be 3-letter English word `the`. Now that we have a few letter, I'll first turn every other instances into the right letter.

```
🌳 = t
🌲 = h
🌴 = e
🌵 = space
```

`the 🎄🌿☘️🍀🍃e🍂 🍁🪴e 🌱e☘️🍂e🌾 the 🎋🎍🪴🌱🍂 🍁🪴e 🍂🎍☘️🍀🎍☘️🍀🪵 the 🍂🍃ee🪨🍃e🍂🍂 ☘️🎍🍀ht🍂 🪴⛰️🍁🪴🌾 🍁☘️🌱 the 🍃⛰️🪴🎍🏕️eet🍂 🍂🎍☘️🍀🪵 🎋🌿🍂h🎋🍁🍂h🌺🍂⛰️🌻🌼🍁☘️🌸🌻t🪴ee🍂🌻🍁☘️🌱🌻🏕️🍁☘️🍀🍁🪴⛰️⛰️🍂🪻 🎍☘️ the 🍃🍁☘️🌱 🌱⛰️🦌☘️ 🌿☘️🌱e🪴🪵 🎄🌿🍂t 🌱⛰️☘️🦘t 🍀et 🎋🎍tte☘️ 🎋🌸 🍁 🍂🪨🎍🌱e🪴🪵`

Not yet there, but this helps a lot to the progress. I can already see that `🍁🪴e` could be `are`, let's update the writings first to try that out.

`the 🎄🌿☘️🍀🍃e🍂 are 🌱e☘️🍂e🌾 the 🎋🎍r🌱🍂 are 🍂🎍☘️🍀🎍☘️🍀🪵 the 🍂🍃ee🪨🍃e🍂🍂 ☘️🎍🍀ht🍂 r⛰️ar🌾 a☘️🌱 the 🍃⛰️r🎍🏕️eet🍂 🍂🎍☘️🍀🪵 🎋🌿🍂h🎋a🍂h🌺🍂⛰️🌻🌼a☘️🌸🌻tree🍂🌻a☘️🌱🌻🏕️a☘️🍀ar⛰️⛰️🍂🪻 🎍☘️ the 🍃a☘️🌱 🌱⛰️🦌☘️ 🌿☘️🌱er🪵 🎄🌿🍂t 🌱⛰️☘️🦘t 🍀et 🎋🎍tte☘️ 🎋🌸 a 🍂🪨🎍🌱er🪵`

Now this is where I'm in quite a bind. Here, I tried to make some guesses (educated one, probably), and my first guess is `🍂` is probably an `s`, considering there is `tree🍂` instance, as well as double s right here `the 🍂🍃ee🪨🍃e🍂🍂`, so I just assumed it is an `s`, let's try continuing with that in place.

`the 🎄🌿☘️🍀🍃es are 🌱e☘️se🌾 the 🎋🎍r🌱s are s🎍☘️🍀🎍☘️🍀🪵 the s🍃ee🪨🍃ess ☘️🎍🍀hts r⛰️ar🌾 a☘️🌱 the 🍃⛰️r🎍🏕️eets s🎍☘️🍀🪵 🎋🌿sh🎋ash🌺s⛰️🌻🌼a☘️🌸🌻trees🌻a☘️🌱🌻🏕️a☘️🍀ar⛰️⛰️s🪻 🎍☘️ the 🍃a☘️🌱 🌱⛰️🦌☘️ 🌿☘️🌱er🪵 🎄🌿st 🌱⛰️☘️🦘t 🍀et 🎋🎍tte☘️ 🎋🌸 a s🪨🎍🌱er🪵`

Well, turns out I can already see the flag here `🎋🌿sh🎋ash` it is `bushbash`, the beginning of a flag. Also, I DID miss this one, `a☘️🌱`, there are 4 instances of those, with those in between either space or `🌻`, my guess is that `🌻` is a hyphen, and the 3-letter word is once again English's `and`.

`the 🎄un🍀🍃es are dense🌾 the b🎍rds are s🎍n🍀🎍n🍀🪵 the s🍃ee🪨🍃ess n🎍🍀hts r⛰️ar🌾 and the 🍃⛰️r🎍🏕️eets s🎍n🍀🪵 bushbash🌺s⛰️-🌼an🌸-trees-and-🏕️an🍀ar⛰️⛰️s🪻 🎍n the 🍃and d⛰️🦌n under🪵 🎄ust d⛰️n🦘t 🍀et b🎍tten b🌸 a s🪨🎍der🪵`

Now, guess the rest while still making sense. `b🎍rds`, `🎍 = i`. `bushbash🌺s⛰️🌻🌼an🌸-trees-and-🏕️an🍀ar⛰️⛰️s🪻`, `🌺 = {`, `🪻 = }`.

`the 🎄un🍀🍃es are dense🌾 the birds are sin🍀in🍀🪵 the s🍃ee🪨🍃ess ni🍀hts r⛰️ar🌾 and the 🍃⛰️ri🏕️eets sin🍀🪵 bushbash{s⛰️-🌼an🌸-trees-and-🏕️an🍀ar⛰️⛰️s} in the 🍃and d⛰️🦌n under🪵 🎄ust d⛰️n🦘t 🍀et bitten b🌸 a s🪨ider🪵`

Very close, I can see that `b🌸 a s🪨ider🪵`, is `by a spider.`, and `birds are sin🍀in🍀🪵` is `birds are singing`. Let's wrap this up.

`the 🎄ung🍃es are dense🌾 the birds are singing. the s🍃eep🍃ess nights r⛰️ar🌾 and the 🍃⛰️ri🏕️eets sing. bushbash{s⛰️-🌼any-trees-and-🏕️angar⛰️⛰️s} in the 🍃and d⛰️🦌n under. 🎄ust d⛰️n🦘t get bitten by a spider.`

`🎄ung🍃es` = `jungles`

`the jungles are dense🌾 the birds are singing. the sleepless nights r⛰️ar🌾 and the l⛰️ri🏕️eets sing. bushbash{s⛰️-🌼any-trees-and-🏕️angar⛰️⛰️s} in the land d⛰️🦌n under. just d⛰️n🦘t get bitten by a spider.`

`🌾` is probably `,` and `s⛰️-🌼any-trees-and-🏕️angar⛰️⛰️s`, the `⛰️` is probably `o` and `🌼` is `m`. From this point I can actually get only the flag but finishing the puzzle seems interesting so I'll play in full.

`the jungles are dense, the birds are singing. the sleepless nights roar, and the lori🏕️eets sing. bushbash{so-many-trees-and-🏕️angaroos} in the land do🦌n under. just don🦘t get bitten by a spider.`

Finish it up.

`the jungles are dense, the birds are singing. the sleepless nights roar, and the lorikeets sing. bushbash{so-many-trees-and-kangaroos} in the land down under. just don't get bitten by a spider.`

`bushbash{so-many-trees-and-kangaroos}`, good puzzle!

## Secret hidden website

Description

We have discovered one of our cybervillain's secret websites located at <https://secret-hidden-website.bushbash.cssa.club> but we don't seem to be able to access it. Can you have work out the next step?

**Author:** Alyssa

Writeup

* **Solver:** xanderous

When tested resolving the subdomain, it doesn't resolve normally and is hidden from standard DNS. Then I tried searching for the public Certified Transparency logs on [crt.sh](https://crt.sh/) for the root domain of [bushbash.cssa.club](https://bushbash.cssa.club) and got a hidden subdomain of <http://bushbash.lbrac.h0w-d1d-y0u-f1nd-th1s.rbrac.bushbash.cssa.club>  
![](https://static.zenn.studio/user-upload/66c101347279-20260807.png)  
After I got the subdomain I made a conclusion of the flag of `bushbash{h0w-d1d-y0u-f1nd-th1s}` as the real flag.

## password

Description

We've recovered a device with a usb port. We know the username is `admin` and the password is `password`, but we just can't log in. The info we received was a cobbled mess, maybe something's missing?

Connect to `nc 34.40.133.67 6768` to access.

**Author:** Eisverygoodletter

Writeup

* **Solver:** yuerei

Attempted standard network logins using line feeds (`\n`) and CRLF (`\r\n`).  
Also tried keyboard layout shift (AZERTY, QWERTZ, Dvorak) caused by physical USB hardware configuration.  
The server sat idling, never acknowledging received usernames or presenting password prompts.

Scripted a fuzzing routine to test various line terminators (`\n`, `\r\n`, `\r`, `\x00`) across layout candidates.  
Sending `admin\x00` immediately triggered a response from the server:

```
Error occured during decoding 'not enough input bytes for length code'
```

The challenge name hint **"cobbled mess"** was a direct pun on **COBS**.  
tried sending `admin\x00` and `password\x00` using COBS encoding, but the server still did not respond. After some trial and error, I realized that the server was expecting COBS-encoded packets.  
The final solution was to send the username and password as COBS-encoded packets, which the server would then decode and validate. The following Python script was used to achieve this:

```
from pwn import *

HOST, PORT = "34.40.133.67", 6768

def cobs_encode(data: bytes) -> bytes:
    return b"".join(bytes([len(chunk) + 1]) + chunk for chunk in data.split(b"\x00")) + b"\x00"

def send_cobs(io, payload: bytes):
    packet = cobs_encode(payload)
    log.info(f"> Sending: {packet}")
    io.send(packet)

io = remote(HOST, PORT)

io.recv(timeout=1)
send_cobs(io, b"admin")
io.recv(timeout=1)
send_cobs(io, b"password")

io.interactive()
```

Got the message `#Your flag is bushbash{i_l0v3_C0bs}`

`bushbash{i_l0v3_C0bs}`

## Hack The Vault I

Description

The jungle holds many secrets, some of them as dark as the night ruled by a laughing moon. Ever since the Moss Man committed his atrocious acts, the villagers slept with an eye open, while detective Kane searches for the taunting vaults he left behind. He wants to talk to you, he needs your help: `nc 34.40.133.67 7776`.

**Author:** Harold Gao  
[vault](https://bushbash.cssa.club/api/files/local/Mmnkl4FeC1IoCZOjUJTwS?iat=1786075800&sig=8O8srC4VfoINLtjRxQqa7rHjawZmBM9mTvlGPl7X4LQ)

Writeup

* **Solver:** yuerei

Just open the vault file and you will find the password th3M0ssM4ni5h3re,y0uc4ntcatchm3.  
![Hack The Vault I Challenge Image](https://static.zenn.studio/user-upload/d17dc53d9e16-20260807.png)  
Putting it on the remote server will give you the flag.

`bushbash{th1s-is-just-th3-beginning!}`.

## The CSSA Hackerman I

Description

![](https://static.zenn.studio/user-upload/242e0456faea-20260807.png)

The CSSA Hackerman is on the run! After successfully hacking into the CSSA Mainframe™, the Hackerman is now making a desperate escape from the CSSA Common Room.

Soon, the Hackerman will be dashing through the suburbs of Canberra, and we need your help hunting them down.

The flag is the coordinates where the Hackerman is standing, to four decimal places. For example, accepted flags would be `bushbash{-35.3081,149.1244}` or `bushbash{-35.3082,149.1244}` if the Hackerman were standing underneath the Australian Parliament House flagpole.

**Authors:** Cameron & Vals  
[aba45f2022fa2a4f28ca87b2cf1a1436.JPEG](https://bushbash.cssa.club/api/files/local/5Wjnkc1da7q-Lk1LL2bUK?iat=1786080600&sig=PiQRXs2LLIW0n8Z4kROo7Xbdh2mYVDGKiqLqvgaZIE8)

Writeup

* **Solver:** Zillaa

The first thing that I did was to look at the surroundings. There is a building behind where the hackerman is standing and a piece of the building’s name called Skaidrite, so I searched for that name on google.  
![](https://static.zenn.studio/user-upload/78f79af7cb15-20260807.png)  
After I searched that name on google, I immediately found the building from the ANU (Australian National University) website and got the full name as Skaidrite Darius Building. I looked it up and the building has the same structure and color so I searched for the location using google maps. The building has 2 sides with the same structure but has a different street/ground in front of the building. The first side has grass and dirt with small pavement and the second side has a street with car parks. From the picture, I can see that in front of the building there is a street, not grass or dirt so I looked for the second side of the building.  
![](https://static.zenn.studio/user-upload/e0f764e49352-20260807.png)  
From the picture, I saw the position of the hackerman and it is slightly left from the building because there is a side pavement with some bushes like the image from the google maps and i just searched the nearest coordinate of the hackerman and got -35.275390 , 149.120934. Because the question asked for only 4 decimal places, I rounded the coordinates and got the flag `bushbash{-35.2754,149.1209}`.

## The CSSA Hackerman II

Description

![](https://static.zenn.studio/user-upload/97b1bf16ebf6-20260807.png)

After making a daring escape from the common room, the CSSA Hackerman hopped into his getaway car, which screamed away at 88mph.

The CSSA, of course, follows the speed limit at all times, so the getaway car got a pretty good head start. Confident that we're off their tail, the Hackerman is taking a rest stop by a lake.

The flag is the coordinates where the Hackerman is resting, to four decimal places. For example, accepted flags would be `bushbash{-35.3081,149.1244}` or `bushbash{-35.3082,149.1244}` if the Hackerman were standing underneath the Australian Parliament House flagpole.

**Authors:** Cameron & Vals  
[b35da867a03e793b0d7077933fb45c15.JPEG](https://bushbash.cssa.club/api/files/local/OsHV3_wBll-m8-A1RQXXo?iat=1786080600&sig=u5OQ0eo3CUKijLOthOLVagbOeOnF8eBFeIqhXSSxj5U)

Writeup

* **Solver:** Zillaa

So the first thing that i do is using google lens to find the location, the lake and skyscraper in the image directs to belconnen ACT, Australia. So I searched it up on google maps. On the google maps, Belconnen is still too vast for me to search the hackerman position, but there is a clue from the image. In the image, the hackerman is looking at a view with a lake and skyscraper, which means the hackerman is on the other side of the lake. There is only one lake at Belconnen which is Lake Ginninderra and so I searched for the hackerman’s position.  
![](https://static.zenn.studio/user-upload/82871be87e81-20260807.png)  
There are 2 places that could be the hackerman’s position. The way to find the similar/exact position is to use the street view on google maps. The first location is way too far from the hackerman’s real position. To narrow the choices, I searched up for the skyscraper that the hackerman is seeing and I got The High Society Apartment. To find the similar location, I saw the angle of the image that the High Society is in front of the hackerman, which means in my assumption the hackerman is directly in front of the High Society, which gave me the second location.  
![](https://static.zenn.studio/user-upload/4b27f67f106d-20260807.png)  
After I used the street view, I couldn't find the exact location where the hackerman was, so I just used the nearest coordinate. I found one place that has the same building as in the image so I used the coordinates for the flag and got the flag `bushbash{-35.2356,149.0729}`.  
Left building -> ![](https://static.zenn.studio/user-upload/9bef3f05fe36-20260807.png)

## The CSSA Hackerman III

Description

![](https://static.zenn.studio/user-upload/7299a954983f-20260807.png)  
Confident there's no one after them, the CSSA Hackerman and the getaway driver are retreating to their evil lair.

The flag is the coordinates where the Hackerman is standing, to four decimal places.

**Authors:** Cameron & Vals  
[att.BLHCuGp7oFzXm4J8xISgq8cLfMHc97LSrm8kKLMgvZQ.JPG](https://bushbash.cssa.club/api/files/local/3atAAaOsYPEXr63_6dp9-?iat=1786077000&sig=-Zx47CuXYOtVKBYw0HAd75Ay5D8L7dG93oAjFi2im6E)

Writeup

* **Solver:** xanderous

First, I tried to find the location of the picture using Google Lens to at least know where it is located. It directs to the location of Australia, and explained that it's possibly located in Canberra as the tree is simillar there. After that, I tried to find the exact location by keep on searching through Google Maps until I find the exact coordinated of the location (it wasted me a lot of time). The coordinates of the location is -35.278353,149.1443443, and so I input the flag for the CSSA Hackerman III `bushbash{-35.2783,149.1443}`.

* TeraP: "goated just finding it straight with Lens and *lots* of searching somehow"

## Signal Haze

Description

We heard you've gotten lost out in the bush again. We're sending a little something to you that may prove useful... However, due to the sensitive nature of this operation we cannot tell you how to extract this information from this transmission. We trust you will be able to figure out out though...

**Authors:** Vals and oreophone  
[data.file](https://bushbash.cssa.club/api/files/local/qFsMxskzfkqf9XLzUEfgP?iat=1786078200&sig=wp88rDzPTRqmQVPN979-suKQy3AiHvFOPrlBEMBia3I)

Writeup

* **Solver:** yuerei  
  Checked file type on cyberchef and it is an audio file (.ogg) The file `data.ogg` was loaded into Audacity and viewed in Spectrogram mode. The spectrogram did not reveal a hidden image directly. Instead, it revealed that the audio is a Slow-Scan Television (SSTV) signal. Using Robot36 on my phone and playing it back, the flag revealed itself.  
  ![](https://static.zenn.studio/user-upload/27a90dabfad3-20260807.png)  
  `bushbash{gR0und-cOntr0l}`

## chip

Description

We've measured some electrical signals from one of cybervillain Zoowee Blubberworth's designs. The chip's markings were sanded off but we can tell that it's still pretty new and possibly has valuable data on it. Can you figure out what chip it is?

Flag format is `bushbash{<manufacturer-name>, <chip-name>}`

All text should be lowercase. Do not include chip packaging information, for example if the manufacturer is bingus and the name of the chip is `ABC12W3R4-TR`, only include the chip name (`ABC12W3R4`) and the flag would be `bushbash{bingus, abc12w3r4}`. Any spaces should be substituted with underscore `_`.

**Author:** Eisverygoodletter  
![](https://static.zenn.studio/user-upload/45512c2afbec-20260806.png)

Writeup

* **Solver:** TeraP

Since I don't know anything about this chip stuff, I first do some research using Google Lens to know what this is. Google Lens result: ![](https://static.zenn.studio/user-upload/1aa8c4be6ba0-20260806.png)  
I can safely conclude this is something called "Timing Diagram", now to actually know what the erased markings are, I decided to search more about this and found this image:  
![](https://static.zenn.studio/user-upload/0f2ae9d27887-20260806.png)  
and a cleaner version, using the four information that actually appears in the image, albeit seemingly to have different order:  
![](https://static.zenn.studio/user-upload/52fa8b570c12-20260807.png)  
I found out that the "?" markings in order is: CS, MISO, SCLK, MOSI. Now, since I've read some articles that CS is basically the start/end of a "recording", we only need to look in place where CS is active (signified by a low level shape). I have also researched that we can identify the [manufacturer and device ID](https://www.linkedin.com/pulse/developing-spi-flash-memory-applications-practical-guide-david-zhu-0rzgc/) from the first 8 bits sent by the controller on MOSI, and counted (manually) that the active window is 32 bits, or 4 bytes.  
So, what we actually need right now is identifying the bytes sent on MOSI and looking up their names in Google. To do this, I decided to try and read the black pixels on the image first, since it looks vector-style rendered and probably nothing will go wrong.

unknown-chip.py

```
from PIL import Image
import numpy as np
    
dark = np.array(Image.open("unknown-chip.png").convert("RGB")).astype(int).mean(axis=2) < 140
rows = [y for y in range(dark.shape[0]) if dark[y].sum() > 300]
print(rows)
```

with the output: `[91, 101, 120, 130, 149, 159, 178]`. It is exactly 19px apart (high to low) for each pairs, so reading the pixels work. But wait, there are only 7 numbers from the supposed 8 (4 pairs), and it seems like the high level of CS doesn't appear because its only there for a few dozen columns, so I will add them manually, and we get: CS (72, 91), MISO (101, 120), SCLK (130, 149), MOSI (159, 178). Now, since the reading is working let's turn the image into actual data we can read.

unknown-chip.py

```
from PIL import Image
import numpy as np

img = np.array(Image.open("unknown-chip.png").convert("RGB")).astype(int)
dark = img.mean(axis=2) < 140

CHANNELS = {"CS": (72, 91), "MISO": (101, 120), "CLK": (130, 149), "MOSI": (159, 178)}

def column_states(hi, lo):
    h = dark[hi-1:hi+2].any(axis=0) # added ±1 to survive antialiasing
    l = dark[lo-1:lo+2].any(axis=0)
    return ['X' if h[x] and l[x] else '1' if h[x] else '0' if l[x] else '.'
            for x in range(img.shape[1])]

st = {name: column_states(*rc) for name, rc in CHANNELS.items()}
for name in ("CS", "MISO", "CLK", "MOSI"):
    print(name.ljust(4), "".join(st[name][70:170]))
```

Here, `X` = hi-Z (both dark), `1` = high only, `0` = low only, and `.` = empty gaps. In the code I only sampled from column 70 to 170, and the result is expected:

```
CS   1111111111....00000000000000000000000000000000000000000000000000000000000000000000000000000000000000
MISO XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
CLK  000000X111111111111111111X000000000000000000X111111111111111111X000000000000000000XX1111111111111111
MOSI XXXXXXXXXXX1111111111111111111111111111111111111....00000000000000000000000000000000000....000000000
```

Now, since I already counted beforehand that the active window is 32 bits, we can just straight up use `X` for each tick, and read both MOSI and MISO channels. First up, recovering the clock:

```
clk = [c if c in '01' else None for c in st['CLK']]
for i in range(len(clk)):
    if clk[i] is None:
        j = i
        while j < len(clk) and clk[j] is None:
            j += 1
        clk[i] = clk[j] if j < len(clk) else '0'

falling = [i for i in range(1, len(clk)) if clk[i] == '0' and clk[i-1] == '1']
```

Then, sample the channels (MOSI and MISO) on falling edges:

```
def sample(chan, x, w=6): # 6px clearance
    v = [chan[k] for k in range(x-w, x+w+1) if chan[k] in '01']
    return max(set(v), key=v.count) if v else '?'

mosi = ''.join(sample(st['MOSI'], e) for e in falling)
miso = ''.join(sample(st['MISO'], e) for e in falling)
print("MOSI:", mosi)
print("MISO:", miso)
```

With the output:

```
MOSI: 10011111????????????????????????
MISO: ????????111011110100000000010101
```

We have successfully uncovered `10011111` from MOSI, which hex is `0x9F`, and from the [LinkedIn earlier](https://www.linkedin.com/pulse/developing-spi-flash-memory-applications-practical-guide-david-zhu-0rzgc/), or this image:  
![](https://static.zenn.studio/user-upload/7d5e59219f86-20260807.png)  
We know that `0x9F` is exactly what we are looking for, so read the MISO after that:

```
- 11101111 = 0xEF
- 01000000 = 0x40
- 00010101 = 0x15
```

Google them up to find the correct chip. And I found this [website](https://wx.comake.online/doc/doc/SigmaStarDocs-SSD220-SIGMASTAR-202305231834/platform/BSP/Ikayaki/SupportList_en.html) which has the exact data:  
![](https://static.zenn.studio/user-upload/2b48ceb9597a-20260807.png)  
Then, searching for any of [W25Q16JV](https://docs.rs-online.com/dea4/0900766b81622f8e.pdf) or W25Q16DV, we will find the manufacturer. And so, the manufacturer is Winbond, and I'll try both W25Q16JV and W25Q16DV for the candidate flag.  
`bushbash{winbond, w25q16jv}` (this is the correct flag, on first try).  
Full solver script:

unknown-chip.py

```
from PIL import Image
import numpy as np

img = np.array(Image.open("unknown-chip.png").convert("RGB")).astype(int)
dark = img.mean(axis=2) < 140

CHANNELS = {"CS": (72, 91), "MISO": (101, 120), "CLK": (130, 149), "MOSI": (159, 178)}

def column_states(hi, lo):
    h = dark[hi-1:hi+2].any(axis=0) # added ±1 to survive antialiasing
    l = dark[lo-1:lo+2].any(axis=0)
    return ['X' if h[x] and l[x] else '1' if h[x] else '0' if l[x] else '.'
            for x in range(img.shape[1])]

st = {name: column_states(*rc) for name, rc in CHANNELS.items()}

clk = [c if c in '01' else None for c in st['CLK']]
for i in range(len(clk)):
    if clk[i] is None:
        j = i
        while j < len(clk) and clk[j] is None:
            j += 1
        clk[i] = clk[j] if j < len(clk) else '0'

falling = [i for i in range(1, len(clk)) if clk[i] == '0' and clk[i-1] == '1']

def sample(chan, x, w=6):
    v = [chan[k] for k in range(x-w, x+w+1) if chan[k] in '01']
    return max(set(v), key=v.count) if v else '?'

mosi = ''.join(sample(st['MOSI'], e) for e in falling)
miso = ''.join(sample(st['MISO'], e) for e in falling)
print("MOSI:", mosi)
print("MISO:", miso)
```

## Conclusion

* TeraP: "Really good CTF, balanced well between easier and more difficult challenges. Can't say I've done a lot though, most of the challenges are done by my friends (especially yuerei) and since I was mostly outside throughout the whole CTF. Regardless, a really good one for fun. Also is it fair web only got 2 chall while rev got 6? 😭😭"
* xanderous: "Amazing CTF, challenging and also brainstorming. My team, Bao Bao, did an amazing job. Even though, mostly my friends do the job, I still feel grateful for the experience that BushBash and also my team has given to me. Thankyou for the enjoyful experience!"
* Zillaa: "good ctf especially for first experience in participating ctf. Even though i only solve 3 problems, it is still amazing to brainstorming and solving a problem. For me this ctf is good for first experience and for training"
* yuerei: "The mix of challenge difficulties was super well-crafted, and the hidden easter eggs made the entire grind a blast. Still lots to learn in web security and reverse engineering, but excited to keep building skills for the next one! 🌙✨"

[![TeraP](https://static.zenn.studio/user-upload/avatar/2a29296d8a.jpeg)](/tera_p)

[TeraP](/tera_p)

バッジを贈って著者を応援しよう

バッジを受け取った著者にはZennから現金やAmazonギフトカードが還元されます。

バッジを贈る

### Discussion

![](https://static.zenn.studio/images/drawing/discussion.png)

[![TeraP](https://static.zenn.studio/user-upload/avatar/2a29296d8a.jpeg)](/tera_p)

[TeraP](/tera_p)

バッジを贈る

[バッジを贈るとは](/faq/badges)

目次

1. [Introduction](#introduction)
2. [Event Overview](#event-overview)
3. [Solved Challenges (21)](#solved-challenges-(21))
4. [Beat Around The Bush](#beat-around-the-bush)
5. [Secret hidden website](#secret-hidden-website)
6. [password](#password)
7. [Hack The Vault I](#hack-the-vault-i)
8. [The CSSA Hackerman I](#the-cssa-hackerman-i)
9. [The CSSA Hackerman II](#the-cssa-hackerman-ii)
10. [The CSSA Hackerman III](#the-cssa-hackerman-iii)
11. [Signal Haze](#signal-haze)
12. [chip](#chip)
13. [Conclusion](#conclusion)