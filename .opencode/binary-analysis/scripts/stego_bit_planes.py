#!/usr/bin/env python3
"""图像位平面遍历提取（stegsolve 的 CLI 等价物）。

对 PNG/BMP/RGB 图像提取 R/G/B 各通道 × bit0-7 的位平面并渲染为灰度图，
肉眼/OCR 检查隐藏内容（LSB 隐写定位标准步骤）。支持输出目录批量落盘。

用法:
  python3 stego_bit_planes.py input.png -o planes/          # 全部 24 平面
  python3 stego_bit_planes.py input.png -o planes/ -c RGB -b 0   # 三通道 bit0（LSB 常驻位）
  python3 stego_bit_planes.py input.png -o planes/ --combine      # RGB bit 平面叠彩色图

依赖: pip install pillow
"""
import argparse
import os
import sys
from dataclasses import dataclass
from enum import Enum

try:
    from PIL import Image
except ImportError:
    print("ERROR: pillow 未安装——pip install pillow", file=sys.stderr)
    sys.exit(1)


class Channel(Enum):
    R = 0
    G = 1
    B = 2


@dataclass
class PlaneSpec:
    channel: Channel
    bit: int

    @property
    def name(self) -> str:
        return f"{self.channel.name}_bit{self.bit}"


def extract_plane(img: Image.Image, spec: PlaneSpec) -> Image.Image:
    """提取指定位平面: 该位为 1 的像素渲染 255，为 0 渲染 0。"""
    gray = img.convert("RGB")
    px = gray.load()
    w, h = gray.size
    out = Image.new("L", (w, h))
    po = out.load()
    mask = 1 << spec.bit
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            v = (r, g, b)[spec.channel.value]
            po[x, y] = 255 if v & mask else 0
    return out


def combine_rgb_bit(img: Image.Image, bit: int) -> Image.Image:
    """三通道同 bit 平面合成彩色图（RGB 各自 bit 展开到 0/255）。"""
    gray = img.convert("RGB")
    px = gray.load()
    w, h = gray.size
    out = Image.new("RGB", (w, h))
    po = out.load()
    mask = 1 << bit
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            po[x, y] = (255 if r & mask else 0, 255 if g & mask else 0, 255 if b & mask else 0)
    return out


def parse_channels(spec: str) -> list:
    table = {"R": [Channel.R], "G": [Channel.G], "B": [Channel.B], "RGB": [Channel.R, Channel.G, Channel.B]}
    key = spec.upper()
    if key not in table:
        raise ValueError(f"通道参数须为 R/G/B/RGB，收到: {spec}")
    return table[key]


def main() -> int:
    ap = argparse.ArgumentParser(description="图像位平面遍历提取（LSB 隐写定位）")
    ap.add_argument("image", help="输入图像（PNG/BMP/JPG）")
    ap.add_argument("-o", "--outdir", required=True, help="输出目录")
    ap.add_argument("-c", "--channels", default="RGB", help="通道: R/G/B/RGB（默认 RGB）")
    ap.add_argument("-b", "--bits", default="0,1,2,3,4,5,6,7", help="位平面列表逗号分隔（默认 0-7）")
    ap.add_argument("--combine", action="store_true", help="额外输出三通道同 bit 合成彩色图")
    args = ap.parse_args()

    channels = parse_channels(args.channels)
    bits = [int(b.strip()) for b in args.bits.split(",") if b.strip() != ""]
    for b in bits:
        if not 0 <= b <= 7:
            raise ValueError(f"位号须 0-7，收到: {b}")

    img = Image.open(args.image)
    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.image))[0]

    count = 0
    for ch in channels:
        for b in bits:
            spec = PlaneSpec(ch, b)
            path = os.path.join(args.outdir, f"{stem}_{spec.name}.png")
            extract_plane(img, spec).save(path)
            print(f"[+] {path}")
            count += 1
    if args.combine:
        for b in bits:
            path = os.path.join(args.outdir, f"{stem}_RGBbit{b}_combine.png")
            combine_rgb_bit(img, b).save(path)
            print(f"[+] {path}")
            count += 1
    print(f"done: {count} planes -> {args.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
