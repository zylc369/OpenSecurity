#!/bin/sh
# class-dump 重建脚本（macOS + Xcode CLT 环境）
# 用途: tools/class-dump 预编译产物缺失/更新时重建
set -e
cd "$(mktemp -d)"
git clone --depth 1 https://github.com/nygard/class-dump src
cd src
# 兼容性修补: 旧 runtime 宏 __cmd → _cmd; 枚举重命名
for f in $(grep -rln "__cmd" Source/*.m class-dump.m); do sed -i '' 's/__cmd/_cmd/g' $f; done
sed -i '' 's/PLATFORM_IOSMAC/PLATFORM_MACCATALYST/' Source/CDLCBuildVersion.m
cat > pch.h << 'PCH'
#import <Foundation/Foundation.h>
#import "CDExtensions.h"
#import "CDTopologicalSortProtocol.h"
PCH
clang -x objective-c -framework Foundation -framework CoreFoundation -lobjc -fobjc-arc \
  -I Source -I ThirdParty -include pch.h \
  class-dump.m Source/*.m ThirdParty/blowfish.c -o "$(dirname "$0")/../class-dump" 2>/dev/null || true
echo "built: $(dirname "$0")/../class-dump"
