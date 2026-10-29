# 硬件与信号取证 (Hardware & Signal Forensics)

> USB 外设/逻辑分析仪/显示信号/侧信道/音频调制信号取证时加载。

## §1 USB/蓝牙外设重建

- **HID 键盘**: 8B 报告（byte0 修饰 0x22=Shift/bytes2-7 键码; 0x00=松键）; HID 表 0x04-0x1d=a-z; **方向键 0x4F-0x52 跟踪行位置**（0x51 Down 行+1）重构多行文本; 6+ 并发键=速录 chord（Plover 字典）
- **鼠标/笔绘制**: 7B 报告 byte1=模式; 相对位移累加; 模式分层渲染+跳抬笔（距离>50 不连）+放大 5-8x+时间渐变; 点击过滤 `$1=="01"`; matplotlib invert_yaxis。OSK 变体: 鼠标点击屏幕键盘打字——提取点击坐标（按下沿）cumsum 得绝对位置叠加到 OSK 键盘图读按键; 工具 USB-Mouse-Pcap-Visualizer
- **LED Morse（pcap 侧）**: host→device SET_REPORT raw[30] 0x01/0x03; >300ms=dash。视频侧: OpenCV 逐帧固定像素跟踪帧数分档
- **RFCOMM 蓝牙**: btrfcomm 过滤; 头 4B/5B（raw[2]&0x01）; 载荷 order+group 双键排序拼接; USB bulk 分片同构
- **GBA 帧缓冲**: raw[3]==0x06 内存 dump 块→240×160 RGB565（r>>8/g>>3/b<<3）; type 7=音频
- **USB 音频**: `tshark -T fields -e usb.iso.data` → Audacity raw signed 16bit PCM
- **bulk 文件提取**: usb.transfer_type==3 过滤 + tshark -T fields -e usb.capdata 直接出 hex（Leftover Capture Data 字段）

## §2 3D 打印

GCDE（PrusaSlicer .g/.bgcode）: 块结构 type(2)+compression(2)+size(4)[+csize(4)]+类型字段+data+CRC32; 压缩 1=Deflate/2,3=**Heatshrink**（heatshrink2 库 window_sz2=12, lookahead_sz2=4）; 缩略图 PNG/JPEG/QOI（qoif 魔术）。藏匿: G-code 注释/`;TYPE:Custom`/元数据/缩略图。可视化: `grep "^G1"|awk '{print $2,$3}'` 提坐标，**侧投影 XZ/YZ 显浮雕文字**; 视频侧打印头轨迹追踪+2D 直方图。

## §3 显示信号

| 协议 | 结构 | 要点 |
|---|---|---|
| VGA | 800×525（640×480+blanking 必裁）; 5B/样本=RGB+HS+VS | 6bit 颜色偏暗就 ×4 |
| HDMI TMDS | 10bit 符号 | bit9 反转→bit8 XOR/XNOR 链逐位恢复; 三通道分组 |
| DisplayPort | 8b/10b+LFSR | 解扰 x^16+x^5+x^4+x^3+1 初态 0xFFFF; **控制字节 BS=0x1C/BE=0xFB 处复位**; TU 64 列=60 数据+4 开销 |

## §4 物理层串行

- **I2C**: START=SDA 降于 SCL 高/STOP=升; 上升沿采样; 第 9 位 ACK; Saleae/PulseView analyzer
- **UART-in-WAV**: 方波阈值二值化→samples_per_bit（总数/位数）→起始位同步 LSB first; 帧格式逐试; Audacity 识别两级电平
- **Saleae .sal**: ZIP（digital-*.bin+meta.json）; delta 编码变迁流; 波特率=delta 众数; idle 极性反着试
- **Tektronix CSV**: CLK 列（50% 占空比识别）上升沿同步采样数据列——一切同步总线（RGB/SPI）通用
- **Linux input_event**: 24B `<QQHHi`（timeval+type+code+value）; type==1 EV_KEY 且 value==1 按下; input-event-codes.h 映射

## §5 侧信道

- **DPA 简化版**: traces 四维 [pos×guess×traces×samples]——跨 traces 平均→猜测间方差最大采样点=泄漏点→该点功耗 argmax=正确猜测。题面 power/leakage/traces
- **键盘声学**: 能量峰（10ms 窗、间隔≥175ms）→10ms 段 MFCC 40 维（mean+std; 窗口勿大——冲击瞬态）→KNN 对标注参考集分类。参考样本逐个用不平均
- **视频 LED Morse**: 固定像素坐标逐帧跟踪（OpenCV frame[y,x]>200=on），on/off 帧数分档 dot/dash/letter/word

## §6 模拟媒体

- **Voyager 音频成像**: 负向同步脉冲分隔扫描行、幅度=亮度; 行重采样定宽堆叠归一化
- **CD 盘片**: CDDA 两字节值（0x0d/0xa8）→**CIRC 去交织**（不去则文字全乱）→螺旋几何 tr(n)=tr0+n·dtr→极坐标 (r,θ) 累积渲染; 校准图对齐参数（arduinocelentano/cdimage）
- **IBM-29 穿孔卡**: 12×80 网格逐格取样（亮=孔）→zone+digit 查表; 间距用参考孔校准
- **MIDI Launchpad**: key=row×16+col; 0x90/0x80 亮灭; 全灭=字符分隔
- **Flipper .sub**: RAW_Data 滤 0x80-0xFF 噪声+batch 变量展开+hint XOR

## §7 关联文件

- `network-forensics.md` — pcap 侧（USB 抓包同源）
- `steganography-forensics.md` — 媒体载体侧
- `$SHARED_DIR/knowledge-base/platform-reversing.md` — IoT/固件/硬件逆向侧

## §8 RF/SDR IQ 信号处理

- **格式**: cf32=complex64 直读 / cs16=int16 reshape(-1,2)→I+jQ / cu8=RTL-SDR raw
- **管线**: FFT 找带 → **循环平稳定符号率**（fft(|iq|²) 峰=Rs，无需先知调制阶数）→ exp(-2jπf_c t) 频移基带 → FIR 低通 → QAM-16 解调（DD 载波恢复 2 阶 PLL: Kp=2ζθn/Ki=θn²，逐符号 de-rotate→最近点判决→imag(sym·conj(nearest)) 误差; Mueller-Muller 定时）
- **星座诊断**: 圆环=固定频偏 / 螺旋=频偏漂移+增益不稳 / 网格团=已同步仅噪声; DD 恢复 4 重模糊（0/90/180/270 全试）
- **细节**: BW=Rs(1+α); RC 收端直采 vs RRC 匹配滤波; AGC 对齐星座功率; GNU Radio QAM-16 默认映射**非 Gray** 核题给表; 成帧 idle 16 符号周期+起止分隔符 0+nibble 对高先
