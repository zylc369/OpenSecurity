# 隐写分析 (Steganography Analysis)

> 载体（图像/音频/视频/文档/容器/终端输出）疑似藏数据时加载。检测→提取→解码全链路。

## §0 第一步与工具速查

```bash
file carrier.*                                  # 真实类型
exiftool carrier.*                              # 元数据（Software 字段定编辑器→私有格式方向）
strings -n 8 carrier.* | grep -iE "flag|pass|key"
zsteg -a image.png                              # PNG/BMP 全平面自动扫（LSB 不只在 bit0，bit5 也常见）
zsteg 1.png -E b1,r,lsb,xy > out.bin            # 指定通道提取; 栈报错 "stack level too deep" 时 --msb 或 -o xY 换扫描顺序
steghide extract -sf image.jpg                  # JPEG 通用提取（info 子命令交互查有无嵌入）
stegseek image.jpg /usr/share/wordlists/rockyou.txt   # steghide 密码爆破（比 stegcracker 快）
outguess -k pass -r stego.jpg out.txt           # outguess 提取（-d 写入; PPM/PNM/JPEG 载体）
stegbreak -r rules.ini -f dict.txt -r p img.jpg # jphide 密码爆破（与 stegdetect -t jopi 配套）
python3 $SHARED_DIR/scripts/stego_bit_planes.py img.png -o planes/   # R/G/B×bit0-7 位平面渲染（项目脚本）
python2 lsb.py extract 0.png out.data <hexkey>  # cloacked-pixel 加密 LSB（zsteg 见乱码 hex 时试; AES 加密需密钥）
```

- 两张相似图 → Image Combiner **and/or/xor 三算法 × RGB 通道全试**（差异显形）; 除文件大小外完全相同的两张图 → 盲水印（BlindWaterMark 脚本 py2/3 不通用/PuzzleSolver 四模式/单张图也可能藏）
- BMP 分析前先转 PNG 再 zsteg（格式转换有时直接揭示）
- 帧数完全平方数的 GIF → 调色板编码; 帧间细微差异 → 帧差分（§6）
- 在线一把梭 aperisolve.fr（多算法并排: LSB/EOF/steghide/outguess/exif）; 小众工具: PixelJihad（在线有密码隐写）/OurSecret/DeEgger Embedder（extract files）/silenteye（识别: 放大后行列不对齐的小灰块; 默认密码 silenteye）

## §1 PNG 结构层

**chunk 解析模板**（一切操作基础）:
```python
import struct
data = open('image.png','rb').read(); pos = 8
while pos < len(data):
    length = struct.unpack('>I', data[pos:pos+4])[0]
    ctype = data[pos+4:pos+8]; cdata = data[pos+8:pos+8+length]
    pos += 12 + length          # +4 type +4 crc
```

| 攻击面 | 识别 | 操作 |
|---|---|---|
| 高度/CRC 篡改 | 图"被裁过"/IHDR CRC 校验失败 | 爆破 h∈1..4096 对 CRC32; CRC 也改过则直接放大 height+重算 CRC |
| 宽高反算（无 CRC 可用时） | JPG/PNG 显示尺寸与文件大小对不上 | 文件字节−头尾开销 ≈ 像素数×3（RGB）: `(size-56)/3/已知宽=真实高`; JPG 也可 010 模板 SOF0 的 `word y_image` 直接改大（不毁图，秒杀法） |
| GIF 多帧宽高 | 分帧数>1 且图被裁 | 每帧 Logical Screen Descriptor 各有宽高字段——逐个全改，只改第一帧无效 |
| 多 IDAT 疑似藏数据 | §1 python chunk 解析器列异常块（长度/顺序） | python 重写 chunk 流: 逐个剔除末尾小 IDAT 重算 CRC 拼新文件试显示; 或合并全部 IDAT 后 $(dirname $PYTHON_CMD)/binwalk 再扫 |
| chunk 乱序 | 头合法但解码报错 | 重排 签名+IHDR+辅助+IDAT(原序)+IEND |
| CRC 字段藏数据 | 各 chunk CRC 是可读 ASCII | 拼接 CRC 字节 |
| 自定义 chunk | 类型非标准集（如 scRT） | 提取 data（可能 XOR 分层加密，见 §8） |
| Fireworks 私有块 | exiftool Software=Adobe Fireworks CS6 | Fireworks 开图层（version-sensitive，已停产） |
| APNG 多帧 | 数据含 acTL（后 4B=帧数） | `apngdis image.apng` 或 python apng 库; 查看器只显默认帧 |
| 签名/chunk 大小写损坏 | §1 解析器按 offset 报错（chunk 长度/CRC） | dd 补 8B 签名; idat→IDAT（首字母大写=critical，小写被当 ancillary 跳过）|
| IDAT 异常小块 | §1 解析器列块: 倒数第二块未满（<65524）后还有小 IDAT | 多余小块 data 单独 `zlib.decompress`（剔除 4B length+4B type+4B CRC）——正常块写满才开新块 |
| BMP 宽高修复 | BMP 显示尺寸与 bfSize 对不上 | 头部修复三路: ①`(bfSize-bfOffBits)//channel//已知宽=真实高`（channel=biBitCount/8）反推宽/高/方根三元组全存; ②删文件头存 `.data` 后 GIMP raw 打开手调宽高; ③同法适用一切"无头像素流"（相机 ARW/mspaint dump 改 .data） |
| GIF 帧间时间轴 | 动画无视觉异常但帧 delay 只有两三种值 | `identify -format "%s %T\n" x.gif` 列每帧 delay，两值映射 0/1 转 ASCII |
| GIF 逐帧 comment | strings 见 GIF89a 后跟异常 hex | `identify -format "%s %c\n" x.gif` 逐帧提 comment（可藏 RSA key 分片）|

## §2 图像位平面与频域

- **JPEG DQT 未引用表**: ID≥2 量化表 SOF 不引用但数据存活; PIL `img.quantization` 或手工扫 0xFFDB（首字节低 4 位=表 ID）; 逐值 LSB
- **BMP 多位平面 QR**: bit 0/1/2 × RGB 全扫（QR 常在 bit1）; `((px>>bit)&1)*255` 渲染后 zbarimg; BMP 无压缩伪影是位平面首选载体
- **F5 统计检测**: jpegio 取 Y 通道 AC 系数，±1/±2 比 <0.10 判 F5（自然 0.25-0.45）; 稀疏图（>80% 零系数）改 ±2/±3 <2.5 副指标
- **种子置换多平面**: `RandomState(SEED).shuffle` 定访问序 + Y 通道 + bitplane 交错（bit0,bit1 交替）; seed 藏 EXIF/文件名/尺寸或小范围爆破; 无 seed 输出纯噪声
- **条件 LSB**: 载体像素过滤（如 R≤1∧G≤1∧B≤1 近黑）——全像素 LSB 工具全漏，过滤条件是关键
- **跨通道多位 LSB**: 各通道不同 bit 位（R[0]G[1]B[2] 循环移位）每像素 3bit; zsteg 全平面全空但 metadata 明示有隐写时用 stego_bit_planes.py 枚举通道×bit 组合
- **RGB 奇偶**: (R+G+B)%2 渲染二值图（题面提 pairs/adding colors）
- **JPEG slack space**: 尺寸向上取 8 倍数（253×195→256×200），padding 像素黑白=bit; `magick -define jpeg:size=256x200` 或 jpeg_uncrop 取全块; payload 结构 2B magic+1B keylen+key+1B msglen+msg
- **JPEG 缩略图掩码**: `exiftool -b -ThumbnailImage` 抽缩略图，暗像素 (x,y) 索引主图 OCR 文本 text_lines[y][x]（选字密码）
- **JPEG 单 bit 翻转爆破**: 8×size 全候选; 缩略图/解码预筛+tesseract OCR; `0xFF` 后必跟 `0x00`/marker——违反处即损坏点
- **窄图行式二进制**: 图宽 7-8 像素 = 每行一个字符的强信号（7-bit/8-bit ASCII，行内亮=1 暗=0）; 7 宽行左补 0; 红通道/亮度阈值 128 都试
- **BF 图片隐写 bftools**: 像素色值经查表映射回 Brainfuck 指令（Braincopter: PNG 像素→8 指令; Brainloller: 色轮旋转方向→指令+转向）。解码: `bftools decode braincopter flag.png` / `decode brainloller` → 输出 BF 文本再解; `bftools decode -o out.txt` 落盘。识别: 图像无统计异常但题面暗示程序/指令、或图片由纯色块规则拼接

## §3 图像拼合与重建

- **拼图重组**: 边缘差分相容矩阵+贪心（难加回溯）或 python 贪心/遗传自动求解（相容矩阵+回溯）; 位图 carve → `convert +append` 横拼 → gaps; 产物可能再叠 ROT13。**碎纸条高速变体**: 每条左右缘编码二进制 bitmask（暗像素=1 逐 y 位移位）→ 相邻边 XOR+popcount（Hamming）贪心拼接——100 条毫秒级
- **QR tile 重排**: finder pattern 三角锚定+timing pattern 定向优先; 小网格（3×3/4×4）全排列×zbarimg 爆破; tile 带旋转时先结构锚定。**无索引变体补集**: ①分块编号藏目录名——目录名像随机串时 `base64 -d` 解出数字索引（MDAx→001），按索引排序拼接免结构分析; ②有索引但大网格时用 codeword 约束回溯代替全排列——按 QR spec 每个 payload 长度找不变像素（finder/timing/alignment 先固定约 50%），剩余块在像素约束下回溯。**1px 列碎片剪枝**: V1 format string 仅 32 合法值（ECC×mask）——列 8 与 32 值集匹配先过滤，剩余少量再全排列。**大图批量 tile 扫描**: PIL crop 按网格切块 → 每块 `resize((500,500))` 放大后 pyzbar 才识别（小块分辨率不足 zbar 不识别）; `Image.ANTIALIAS` 需 pillow≤9.5.0（新版已移除该常量改 `Image.LANCZOS`）。定位角缺失时手画三个 7×7 回字补全（左上/右上/左下）
- **像素坐标链**: R=数据/G,B=下一坐标（变体 G*256+B 宽图）; G/B 通道小数值结构化分布是识别信号
- **RGB 文本像素点合成**: 纯文本每行 `R,G,B` 十进制值（无图片结构）——行数做整数分解猜宽高（x*y=行数，逐因子对试），PIL `putpixel((i,j),(r,g,b))` 重建; 长度先修成平方数也是信号
- **视频帧差分时域**: 逐帧逐像素 +1=1/不变=0; `ffmpeg -i video.avi frame_%04d.png` 拆帧后 diff; 单帧工具全漏

## §3a 插值与 resize 域

- **等距网格隐藏图**: 隐藏像素按间隔分布，最近邻降采样只取隐藏像素（双线性混合毁数据）; `magick -interpolate nearest-neighbor -interpolative-resize`; 间距与尺寸取 GCD
- **嵌套 resize 幸存像素**: PIL NEAREST 每块幸存一个像素（10× 缩小幸存位 (10i+7,10j+7)）——第二 QR 写在幸存位，不同缩小层级解出不同 QR; 偏移 floor(orig×scale)+0.5 先算

## §3b 调色板元数据通道

- 核心概念: 数据藏元数据通道而非像素通道，绕过 LSB 检测。PNG 未引用 PLTE 条目 R 通道 ASCII（`used=set(img.getdata())` 取补集）; GIF 逐帧 PLTE body 拼接成 ELF（像素数据无关）; 任何"多帧+每帧元数据"格式（APNG fcTL/PDF 页流/MKV 轨道）同面——chunk 级 dump 先于像素分析

## §4 音频

**三板斧（按序）**: ①频谱图 `sox x.wav -n spectrogram -o spec.png`（文本/QR 常在 2-15kHz; Sonic Visualiser 可调窗长） ②样本 LSB `stegolsb wavsteg -r -i a.wav -o out.bin -n 2 -b 1000`（显式信号如 SSTV 可能是诱饵——找到一种编码后仍查 LSB） ③DeepSound（WAV 载文件+AES; `deepsound2john.py` 提 hash→john 爆破）。

- **MP3 载体 MP3Stego**: `encode -E hidden.txt -P pass in.wav out.mp3` 写入 / `decode -X -P pass stego.mp3` 提取——MP3 帧层隐写，WAV 三板斧全部无效。密码常在文件 strings/ID3 tag 里给到; 识别: WAV 分析无果且为 MP3 即转 MP3Stego。旧工具 Silenteye 同类（WAV/BMP LSB+AES，GUI）。**爆破坑: MP3Stego 错密码同样产出文件——不能用"有无输出"当判据，须逐个打开检查内容**（脚本爆破每密码存不同输出名再验）; SilentEye 解密失败时换音质 low/high × AES128/256 四组合试。立体声音轨摩斯: Audacity 分离立体声到单声道（Shift+M）后独奏第一轨。DeepSound 同类工具; 摩斯音频自适应解码 morsecode.world/international/decoder/audio-decoder-adaptive.html
- **波形目测**: 高低/长短双形态直接映射 01 或 Morse 点划（位数为 7 倍数→7 位一组转 ASCII; 长短空→Morse 再栅栏）

- **双轨差分**: 两近似音轨反相相减显形: `sox -m t0.wav "|sox t1.wav -p vol -1" diff.wav` → gain -n -3 → 高分辨频谱 `-X 2000 -Y 1000 -z 100 -h` → `sinc 5000-12000` 滤带。陷阱: metadata 诱饵 flag / 声道标签造假 / 窄时间窗
- **DTMF 标准+自定义**: 标准 `sox → multimon-ng -t raw -a DTMF`（# 后常八进制 ASCII）; 自定义频率先 showspectrumpic 目测等距网格→按窗 rfft 双峰→行列键值→变长数字转 ASCII（2-3 位贪心 32≤v≤126）。**双层变体**: DTMF 解出的数字串再走 T9 多击键盘（'44'=h、'7777'=s; 停顿分隔同键连击）
- **手工编码四式**: FFT 主频→音名（A4=440）首字母拼词; MIDI note_on/off pitch 对 `chr(on+off)`/`(on<<4)|off`/XOR 全试; 两种波形形态=bit; exiftool comment 下划线分隔 0-7 数字=八进制→常叠 base64。**音阶度数变体**: 转写的音符序列按大调音阶度数（D 大调 D=0..C#=6）当 nibble，相邻音符对 `(n1<<4)|n2` 一字符——已知 flag 前后缀校准映射。**bytebeat 生成音乐**: 单行 C 风格表达式含 `t` 变量+%|&^>><< 位运算+8bit 输出即 bytebeat 签名——贴在线解释器（wry.me/bytebeat）播放，曲名即答案
- **高采样率 SSTV 手工解调**: 48/96kHz 标准解码器失败→arccos+diff 算瞬时频率 `freq=diff(arccos(clip(data)))*rate/2π`，1500-2300Hz 线性映灰度
- **图像 FFT 频域**: fftshift+fft2 幅度谱 log(1+|F|); 同心环×固定角度集=bit 位（峰=0 无峰=1）; 阈值按频谱目测

## §5 视频与变换域

- **时域聚合三式**: 帧累加 `np.maximum` 全帧合成（闪烁位置拼图）/ 帧平均浮点累加+N（噪声掩盖内容显形，暗则 ImageOps.equalize）/ 音频倒放（`sox reverse`/`ffmpeg -af areverse`，含糊语调必试）
- **JPEG XL TOC 置换**: TOC 的 Lehmer 置换控制渐进收敛顺序，完整解码不可见; 每 1KB 截断→djxl 解码→与终态比对记 tile 收敛 offset→tile_id 序列=flag
- **Arnold Cat Map**: 方形图+直方图正常但均匀噪声→迭代 (2x+y,x+y) mod N 直到复原（周期整除 3N，大图先解析周期）; 区别于种子置换（无周期靠 seed）
- **MJPEG FFD9 尾部信道**: 按 \xff\xd8 分帧，每帧 EOI 后附加字节拼接; 解码器遇 FFD9 即停
- **EXIF zlib+Stegano 生成器**: ImageDescription(tag 270) base64→`\x78\x9C` zlib 魔术→提示 Stegano 非顺序生成器（triangular_numbers 等）; 行序扫描工具的盲区
- **PDF xref 代数信道**: `offset gen n/f` 中 gen 非 0/65535 即数据; 按 02x 拼 hex→ASCII（乱码试逆序）; pdf-parser.py --raw 防归一化
- **ECB 逐像素哈希恢复**: 灰度 256 值域全枚举预计算 hash→pixel 查表; 密文图保留轮廓结构即确认 ECB 模式
- **多色 QR 2^N 爆破**: N 色各映 0/1，product 全爆×zbarimg; RS 纠错使多个划分都解出有效消息——跑完全部收集所有结果

## §6 通用容器与交织

- **结束标记后 overlay**: PNG IEND / JPEG FFD9 / GIF Trailer / PDF %%EOF 之后皆可疑; 附加区头部魔术被合法签名覆盖时手工改回目标格式魔术（7z=`37 7A BC AF 27 1C`）
- **多流视频容器**: 视频第一步永远 `ffprobe -hide_banner` 枚举全部流; flag 常在 0:1（`ffmpeg -map 0:1`）; 默认流是诱饵、第二流常用冷门编码
- **两层交织**: 双扩展名（.ppnngg）/偶奇字节提出双 PNG 头→先剥字节层，产物横向条纹→再剥扫描行层
- **GIF 帧差分+Morse**: `compare -fuzz 10%` 揭示单像素修改，点大小/间隔映射 Morse
- **GIF 调色板编码**: 帧数完全平方→每帧=1 像素，`gif.getpalette()[0]` 亮度定黑白
- **渐进 PNG 逐层 XOR**: 自定义 chunk（scRT）多字节 XOR 层层嵌套; `xortool -c ff`（图像最频字节 0xFF）; 嵌套 matryoshka 配递增语义 key（layer2/layer3）

## §7 文档类

**PDF 检查清单**: strings 明文 → exiftool 全字段 → pdfimages -all + zsteg -a（LSB 可能在 bit5） → 编辑器查遮盖矩形（删黑块露 QR） → FlateDecode 流 zlib 解压搜 → Link 注释 URI 的 `\{` `\}` 转义还原（pikepdf） → `mutool clean -d` 全解压 → %%EOF 后附加数据 → pdftotext -layout 不可见分隔符 → 模糊图 Wiener 反卷积（skimage wiener+高斯 PSF σ≈3）→ 矢量矩形 QR（内容流 re 算子中心渲染）→ 末层常是 ROT18。

**SVG**: ①微坐标隐藏图形——坐标大量小数聚集极小区间，scale(200,200)+translate 放大 ②动画 keyTimes/values 两色交替=二进制、间隔比 t:3t=Morse 点划。

**表格频率编码**: 单元格数字 unique 恰 256 种→频率名次=字节值，Counter+排序映射恢复 ELF/图片; magic 不上就反转映射/换读取顺序。

**GZSteg**（version-sensitive，gzip 1.2.4 补丁版）: .gz 体积异常大→`gzip --s` 提取→spam 风格文本→spammimic.com 解码。

**wbStego4open**: 载体限 BMP/TXT/HTM/PDF 四种——这四类带密码提示优先试; 编码指纹: 每个二进制位替换为 hex `20`(0)/`09`(1)，文件里大量 20/09 交替 8 位字节即此工具特征。

**RTF ignorable destination**: `{\*\customtag<N> DATA}` 自定义控制序列——标准 RTF 查看器跳过 `\*` 前缀的 ignorable 目标，数据藏在这些被忽略字段; `grep -oP '\\\\\*\\\\[a-z]+\d*'` 找非标准 tag，按 N 排序拼接后常是 base64。

## §8 终端与编码类

- **Kitty 图形协议**: `\x1b_G<hdr>;<b64>\x1b\\`; a=T/q=2/f=24/o=z/m=1(分块)/s=宽,v=高; 多块 m=1 链拼接后 b64decode+zlib → frombytes RGB。检测: `\x1b_G` 序列
- **ANSI 转义隐写**: flag 穿插 ANSI 码与盲文（U+2800-28FF）间，渲染不可见; `re.sub(r'\x1b\[[0-9;]*[a-zA-Z]','')` 剥离后滤可打印 ASCII; `col -b` 渲染 diff 辅助。pcap 变体: `tshark -q -z follow,tcp,raw,0` 抽流后 `more`/`less -r` 渲染即显示光标定位序列拼出的字。同族: 退格符 0x08 隐藏——终端所见≠原始字节
- **立体图 autostereogram**: 重复纹理背景; 单行自相关首峰=shift（80-120px），`abs(img[:,shift:]-img[:,:-shift])` 差分显深度文本
- **边框像素**: 1px 边框黑白=bit，顺时针 top→right→bottom(逆)→left(逆)，阈值 RGB 和 384; 乱码则换起点/方向
- **Unicode 高位不可见区隐写两族**: ①Variation Selectors Supplement U+E0100-U+E01EF——emoji 后跟不可见选择符，`chr((ord(c)-0xE0100)+16)` 提取（+16 偏移）; ②Tags 区 U+E0000-U+E007F——与 ASCII 1:1 镜像直接减 0xE0000，藏 URL fragment/文件名，UTF-8 百分号编码 `%F3%A0%8x` 前缀。共同信号: 文本看着正常但 len() 远大于视觉长度; 同族空白字符隐写（空格/tab/零宽 U+200B）

## §9 密码学交叉与 QR 重建

- **Angecryption**: 构造 AES-CBC key/IV 使文件 A 加密产物也是合法文件 B（头部自由度+CBC IV 自由度）。识别: 两个同格式文件+对称密钥材料; 遮罩图叠加显形
- **QR 手工重建**: 定版本（25×25=V2）→format bits 定 ECC/mask →放大 NEAREST 逐格转录 →20px/格渲染干净 QR →zbarimg; 初解失败用已知明文前缀修前几模块，高 ECC（Q=25%）纠余错。反射先翻转+去畸变
- **Hex 数独+QR 组合**: 多个 QR 各含 16×16 hex 数独的一个象限——解数独（0-F 每行列 4×4 宫各一次，回溯）后主对角线 `grid[i][i]` 拼十六进制串两两成字节转 ASCII。识别: 多 QR 分发+内容是 hex 数字带空格/下划线
- **01 网格文本渲染 QR**: 纯 0/1 字符文本（长度开方验证）→每 bit 一像素、scale 4-8× 渲染 PNG→zbarimg/pyzbar（finder pattern 需足够大才被识别; 0=黑还是 1=黑两种都试）; QR 载荷常是 hex 密文再叠短 key XOR（key 试 `flag`/赛名——密文前几字节 XOR 已知明文 `ctf{` 直接得 key，见 classical-crypto §8.2）
- **汉信码识别**: 似 QR 但**四角都有定位特征且左下角方向相反**（QR 仅三角）——扫不出的"QR"先看角标形态; 在线解码 efittech.com/hxdec.aspx。配套 Excel 显隐路径: 表面空白→改 zip 看 xl/worksheets/*.xml 有实际值→条件格式"文本包含"或单元格格式改"常规"恢复显示→0/1 替换成黑/白方块渲染（Word 版三板斧: 改 zip/全选改字体色/选项-显示-隐藏文字）。**非 QR 二维码全家桶**: Aztec（中心同心圆靶+无静区）/DataMatrix（L 形两边+虚线交替边）/PDF417（高瘦多行条）/GridMatrix——标准 QR 解码器全失败时按定位图形形态对号入座，zxing 库多格式支持; 图片反相后扫不出先 PS 反相

## §10 关联文件

- `$SHARED_DIR/knowledge-base/forensics-methodology.md` — 取证总入口/类型分诊
- `$SHARED_DIR/knowledge-base/classical-crypto.md`（crypto-analysis）— 多层编码链/ROT18 等编码层
- `$SHARED_DIR/knowledge-base/crypto-validation-patterns.md`（crypto-analysis）— XOR 密码分析工具族
