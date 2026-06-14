# arm64 无符号逆向方法论

> 在无符号（stripped）的 arm64 二进制中定位函数和数据的实用方法。适用于 IDA Pro 分析 .so/.dylib 等无符号库。
> 触发条件：目标二进制无符号表，需要通过字符串引用、调用模式定位关键函数。

---

## 1. arm64 字符串引用机制

arm64 使用 PC 相对寻址（ADRP+ADD 指令对）引用字符串，不像 x86 的绝对地址引用。

### 1.1 ADRP+ADD 原理

```asm
ADRP X0, #page@PAGE        ; 加载页地址（4KB 对齐）到 X0
ADD  X0, X0, #page@PAGEOFF ; 加页内偏移得到完整地址
```

- `ADRP` 取当前 PC 值，将低 12 位清零，加上 imm（以页为单位的偏移）
- `ADD` 加上页内偏移，得到最终的字符串地址
- 结果：一条字符串引用对应 **两条指令**

### 1.2 在 IDA 中识别

```asm
; 典型的字符串引用
ADRP    X1, #aTrustBuiltin@PAGE   ; 0xXXXXX
ADD     X1, X1, #aTrustBuiltin@PAGEOFF ; "TrustBuiltinRoots"
BL      sub_XXXXX                   ; 调用某函数
```

在 IDA 反汇编中，ADRP+ADD 通常紧跟在对字符串操作函数的调用之前（如 `strcmp`、`printf`、或内部函数）。

---

## 2. IDAPython ADRP 搜索脚本模板

当 IDA 的字符串交叉引用不可用时（如字符串在 .rodata 中但未被 IDA 识别为字符串），需要手动搜索。

### 2.1 搜索字符串并定位 ADRP 引用

```python
# ida_search_string_adrp.py
# 在 IDA Python Console 中运行
# 用法: 搜索包含指定关键词的字符串，定位所有 ADRP+ADD 引用
import idautils
import idc
import ida_bytes
import ida_search
import ida_idaapi

def search_string_references(keyword):
    """搜索字符串并定位所有引用点"""
    results = []
    
    # 第一步：在所有段中搜索字符串
    for seg in idautils.Segments():
        seg_start = idc.get_segm_start(seg)
        seg_end = idc.get_segm_end(seg)
        seg_name = idc.get_segm_name(seg)
        
        if '.rodata' not in seg_name and '.data' not in seg_name:
            continue
            
        ea = seg_start
        while ea < seg_end:
            s = idc.get_strlit_contents(ea)
            if s and keyword in s.decode('utf-8', errors='ignore'):
                str_addr = ea
                str_val = s.decode('utf-8', errors='ignore')
                print("[+] String found: '%s' at 0x%X" % (str_val, str_addr))
                
                # 第二步：查找交叉引用
                for xref in idautils.XrefsTo(str_addr):
                    caller_func = idc.get_func_name(xref.frm)
                    caller_addr = xref.frm
                    print("    [ref] 0x%X in %s" % (caller_addr, caller_func))
                    results.append({
                        'string': str_val,
                        'str_addr': str_addr,
                        'ref_addr': caller_addr,
                        'func': caller_func
                    })
                break
            ea = idc.next_head(ea, seg_end)
    
    if not results:
        print("[-] No results for '%s', trying binary search..." % keyword)
        # 降级：二进制搜索
        pattern = keyword.encode('utf-8')
        ea = ida_search.find_binary(0, ida_idaapi.BADADDR, 
                                      ' '.join('%02X' % b for b in pattern),
                                      16, ida_search.SEARCH_DOWN)
        while ea != ida_idaapi.BADADDR:
            print("[+] Binary match at 0x%X" % ea)
            for xref in idautils.XrefsTo(ea):
                print("    [ref] 0x%X in %s" % (xref.frm, idc.get_func_name(xref.frm)))
                results.append({
                    'string': keyword,
                    'str_addr': ea,
                    'ref_addr': xref.frm,
                    'func': idc.get_func_name(xref.frm)
                })
            ea = ida_search.find_binary(ea + 1, ida_idaapi.BADADDR,
                                          ' '.join('%02X' % b for b in pattern),
                                          16, ida_search.SEARCH_DOWN)
    
    print("\n[*] Total: %d references found" % len(results))
    return results

# 使用方法
results = search_string_references("TrustBuiltinRoots")
```

### 2.2 反向搜索：从函数找字符串

```python
# ida_func_strings.py
# 列出指定函数引用的所有字符串
import idautils
import idc

def get_func_strings(func_addr):
    """列出函数内引用的所有字符串"""
    func_end = idc.get_func_attr(func_addr, idc.FUNCATTR_END)
    if func_end == idc.BADADDR:
        print("[-] Invalid function address")
        return
    
    print("[*] Strings in function at 0x%X:" % func_addr)
    ea = func_addr
    while ea < func_end:
        # 检查是否是 ADRP 指令
        mnem = idc.print_insn_mnem(ea)
        if mnem == "ADRP":
            # 获取 ADRP 的目标地址
            op_val = idc.get_operand_value(ea, 1)
            # 检查下一条是否是 ADD
            next_ea = idc.next_head(ea, func_end)
            if idc.print_insn_mnem(next_ea) == "ADD":
                add_val = idc.get_operand_value(next_ea, 2)
                full_addr = op_val + add_val
                # 尝试读取字符串
                s = idc.get_strlit_contents(full_addr)
                if s:
                    print("  0x%X: \"%s\"" % (full_addr, s.decode('utf-8', errors='ignore')))
        ea = idc.next_head(ea, func_end)

# 使用方法
get_func_strings(0x8413F8)  # 替换为实际函数地址
```

---

## 3. 从字符串引用定位到函数的完整流程

```
1. 确认目标关键词（如 "TrustBuiltinRoots"、" certificate"、错误消息）
     ↓
2. 在 .rodata 段搜索字符串
     ├── 找到 → 获取字符串地址
     └── 未找到 → 二进制搜索（Search > Sequence of Bytes）
     ↓
3. 查找字符串的交叉引用（XrefsTo）
     ├── 有引用 → 跳到步骤 4
     └── 无引用 → IDA 可能未分析，手动搜索 ADRP 指令
         ↓
         遍历代码段，检查每条 ADRP 的目标页地址是否包含字符串
     ↓
4. 引用点所在的函数就是目标函数
     ├── F5 反编译
     ├── 分析参数和调用链
     └── 继续向上/向下追踪
```

### 3.1 手动 ADRP 搜索（最后手段）

当 IDA 的交叉引用完全不可用时：

```python
# ida_manual_adrp.py
# 手动搜索引用特定地址的 ADRP 指令
import idautils
import idc

def find_adrp_refs(target_addr):
    """搜索所有引用 target_addr 的 ADRP+ADD 指令对"""
    page_addr = target_addr & ~0xFFF  # 4KB 页对齐
    page_off = target_addr & 0xFFF
    
    print("[*] Searching for refs to 0x%X (page=0x%X, off=0x%X)" % 
          (target_addr, page_addr, page_off))
    
    results = []
    for seg in idautils.Segments():
        seg_name = idc.get_segm_name(seg)
        if '.text' not in seg_name:
            continue
        
        seg_start = idc.get_segm_start(seg)
        seg_end = idc.get_segm_end(seg)
        
        ea = seg_start
        while ea < seg_end:
            mnem = idc.print_insn_mnem(ea)
            if mnem == "ADRP":
                op_val = idc.get_operand_value(ea, 1)
                if op_val == page_addr:
                    next_ea = idc.next_head(ea, seg_end)
                    if idc.print_insn_mnem(next_ea) == "ADD":
                        add_val = idc.get_operand_value(next_ea, 2)
                        if add_val == page_off:
                            func = idc.get_func_name(ea)
                            print("[+] ADRP+ADD at 0x%X in %s" % (ea, func))
                            results.append(ea)
            ea = idc.next_head(ea, seg_end)
    
    print("[*] Found %d references" % len(results))
    return results

# 使用方法
find_adrp_refs(0x123456)  # 替换为目标字符串地址
```

---

## 4. arm64 调用约定速查

### 4.1 寄存器用途

| 寄存器 | 用途 | 保存者 |
|--------|------|--------|
| X0-X7 | 函数参数/返回值 | 调用者 |
| X8 | 间接结果地址（大返回值） | 调用者 |
| X9-X15 | 临时寄存器 | 调用者 |
| X16-X17 | IP0/IP1（PLT/链接器） | 调用者 |
| X18 | 平台保留 | — |
| X19-X28 | 被调用者保存 | 被调用者 |
| X29 (FP) | 帧指针 | 被调用者 |
| X30 (LR) | 返回地址 | 被调用者 |
| SP | 栈指针 | — |

### 4.2 函数调用识别

```asm
; 直接调用（短距离）
BL   target_function

; 间接调用（通过寄存器）
BLR  X0

; 尾调用（复用当前栈帧）
B    target_function
```

### 4.3 参数追踪技巧

在 Frida 中 Hook arm64 函数时：

```javascript
// arm64 函数参数对应
// arg1 = args[0] (X0)
// arg2 = args[1] (X1)
// ...
// 返回值 = retval (X0)

Interceptor.attach(targetAddr, {
    onEnter: function(args) {
        console.log("X0:", args[0]);
        console.log("X1:", args[1]);
        console.log("X2:", args[2]);
        // 读取指针指向的内存
        if (!args[0].isNull()) {
            console.log("  *X0:", args[0].readPointer());
        }
    },
    onLeave: function(retval) {
        console.log("Return value (X0):", retval);
    }
});
```

---

## 5. 与其他知识库的关系

- **字符串搜索脚本**：本文件的脚本模板可直接在 IDA Console 运行
- **Flutter SSL bypass**：ADRP 搜索是定位 `TrustBuiltinRoots` 的关键步骤，详见 `$OPENCODE_ROOT/mobile-analysis/knowledge-base/flutter-ssl-bypass.md`
- **IDAPython 编码规范**：脚本编写前建议先读 `$SHARED_DIR/knowledge-base/idapython-conventions.md`
