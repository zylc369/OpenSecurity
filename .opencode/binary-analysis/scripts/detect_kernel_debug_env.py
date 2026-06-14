# -*- coding: utf-8 -*-
"""双机调试环境检测脚本

检测宿主机和 VM 是否满足 Windows 内核驱动双机调试的条件。
输出结构化 JSON，包含每项检测结果和缺失项的修复指引。

不依赖 IDAPython，纯 Python + subprocess 调用 vmrun。

使用方式:
  python detect_kernel_debug_env.py --output env.json
  python detect_kernel_debug_env.py --output env.json --vm-name "Windows 10 x64"

环境变量:
  PRIVACY_DATA: 隐私数据文件路径（默认 .privacy-data/privacy-data.json）

输出格式:
  {
    "ready": true/false,
    "checks": [
      {"name": "vmrun", "status": "ok"|"missing"|"error", "detail": "...", "fix_hint": "..."},
      ...
    ],
    "missing_items": ["vmrun", "kd_exe", ...]
  }
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


def _run(cmd, timeout=15):
    """执行命令，返回 (returncode, stdout, stderr)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace')
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, '', f'命令未找到: {cmd[0]}'
    except subprocess.TimeoutExpired:
        return -2, '', f'超时 ({timeout}s)'
    except Exception as e:
        return -3, '', str(e)


def check_vmrun():
    """检查 vmrun 是否可用"""
    vmrun_path = shutil.which('vmrun')
    if vmrun_path:
        rc, out, _ = _run(['vmrun', '-T', 'ws', 'list'])
        if rc == 0:
            return 'ok', f'vmrun 可用: {vmrun_path}'
        return 'error', f'vmrun 存在但 list 命令失败: {rc}'
    return 'missing', 'vmrun 未找到。请安装 VMware Workstation 并加入 PATH'


def check_vm_running(vm_name=None):
    """检查 VM 是否在运行"""
    vmrun_path = shutil.which('vmrun')
    if not vmrun_path:
        return 'skip', 'vmrun 不可用，跳过 VM 状态检查'

    rc, out, _ = _run(['vmrun', '-T', 'ws', 'list'])
    if rc != 0:
        return 'error', 'vmrun list 执行失败'

    running_vms = [line.strip() for line in out.splitlines() if line.strip() and line.strip() != 'Total running VMs:']

    if not running_vms:
        return 'missing', '没有正在运行的 VM。请启动目标虚拟机'

    if vm_name:
        matching = [v for v in running_vms if vm_name.lower() in v.lower()]
        if matching:
            return 'ok', f'目标 VM 正在运行: {matching[0]}'
        return 'missing', f'目标 VM "{vm_name}" 未运行。当前运行: {running_vms}'

    if len(running_vms) == 1:
        return 'ok', f'检测到 1 个运行中的 VM: {running_vms[0]}'

    return 'ok', f'检测到 {len(running_vms)} 个运行中的 VM: {running_vms}（需指定 --vm-name 选择目标）'


def _find_kd_exe():
    """搜索 kd.exe 路径"""
    # 1. 常见 WinDbg 安装路径
    search_paths = []

    # WinDbg Store 版
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    if local_appdata:
        windbg_base = os.path.join(local_appdata, 'Microsoft')
        if os.path.isdir(windbg_base):
            for d in os.listdir(windbg_base):
                if d.lower().startswith('windbg'):
                    kd_path = os.path.join(windbg_base, d, 'amd64', 'kd.exe')
                    if os.path.isfile(kd_path):
                        return kd_path

    # Windows SDK
    program_files = os.environ.get('ProgramFiles(x86)', '')
    if program_files:
        sdk_base = os.path.join(program_files, 'Windows Kits', '10', 'Debuggers', 'x64')
        kd_path = os.path.join(sdk_base, 'kd.exe')
        if os.path.isfile(kd_path):
            return kd_path

    # PATH 中搜索
    kd_in_path = shutil.which('kd.exe')
    if kd_in_path:
        return kd_in_path

    return None


def check_kd_exe():
    """检查 kd.exe 是否存在"""
    kd_path = _find_kd_exe()
    if kd_path:
        # 检查关键依赖 DLL
        kd_dir = os.path.dirname(kd_path)
        required_dlls = ['dbgeng.dll', 'dbghelp.dll']
        missing_dlls = [dll for dll in required_dlls if not os.path.isfile(os.path.join(kd_dir, dll))]
        if missing_dlls:
            return 'error', f'kd.exe 找到 ({kd_path})，但缺少依赖 DLL: {missing_dlls}'
        return 'ok', f'kd.exe 可用: {kd_path}'
    return 'missing', ('kd.exe 未找到。请安装 WinDbg（Microsoft Store 版或 Windows SDK），'
                        '或手动将 kd.exe 路径加入 PATH')


def _load_vm_config():
    """从隐私数据文件加载 VM 配置"""
    # 按优先级搜索隐私数据文件
    search_paths = [
        os.environ.get('PRIVACY_DATA', ''),
        os.path.join(os.getcwd(), '.privacy-data', 'privacy-data.json'),
    ]

    for path in search_paths:
        if path and os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('kernel_debug_vm', {}), path
            except Exception:
                continue
    return None, None


def check_vm_debug_config(vm_name=None):
    """检查 VM 是否配置了 NET 调试传输"""
    vmrun_path = shutil.which('vmrun')
    if not vmrun_path:
        return 'skip', 'vmrun 不可用，跳过 VM 调试配置检查'

    # 尝试获取 VM 标识
    vmx_path = None
    vm_config, config_path = _load_vm_config()

    if vm_config and vm_config.get('vmxPath'):
        vmx_path = vm_config['vmxPath']
    elif vm_name:
        # 尝试通过 vmrun list 匹配
        rc, out, _ = _run(['vmrun', '-T', 'ws', 'list'])
        if rc == 0:
            running = [l.strip() for l in out.splitlines() if l.strip() and 'Total' not in l]
            matching = [v for v in running if vm_name.lower() in v.lower()]
            if matching:
                vmx_path = matching[0]

    if not vmx_path:
        return 'skip', '无法确定目标 VM，跳过调试配置检查（配置 .privacy-data/privacy-data.json 或指定 --vm-name）'

    # 通过 vmrun runProgramInGuest 检查 bcdedit 配置
    if vm_config and vm_config.get('accountName'):
        guest_user = vm_config['accountName']
        # 密码解码
        import base64
        guest_pass = base64.b64decode(vm_config.get('passwordEncoded', '')).decode('utf-8')
    else:
        return 'skip', '缺少 VM 登录凭据，跳过调试配置检查'

    rc, out, err = _run([
        'vmrun', '-T', 'ws', '-gu', guest_user, '-gp', guest_pass,
        'runProgramInGuest', vmx_path, 'cmd /c bcdedit /dbgsettings'
    ], timeout=20)

    if rc != 0:
        return 'error', f'无法获取 VM 调试配置: {err}'

    has_debug = 'debugtype' in out.lower()
    has_net = 'net' in out.lower()

    if has_debug and has_net:
        # 提取关键信息
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return 'ok', f'VM 调试配置正确: {"; ".join(lines[-3:])}'

    if has_debug and not has_net:
        return 'error', ('VM 调试已启用但传输类型不是 NET。请在 VM 中执行:\n'
                         '  bcdedit /dbgsettings net hostip:<HOST_IP> port:50000')

    return 'missing', ('VM 未配置内核调试。请在 VM 中执行:\n'
                        '  bcdedit /debug on\n'
                        '  bcdedit /dbgsettings net hostip:<HOST_IP> port:50000\n'
                        '  bcdedit /testsigning on\n'
                        '然后重启 VM')


def check_vm_autologin():
    """检查 VM 是否配置了自动登录"""
    vm_config, _ = _load_vm_config()
    if not vm_config:
        return 'skip', '未配置隐私数据，跳过自动登录检查'

    if vm_config.get('accountName') and vm_config.get('passwordEncoded'):
        return 'ok', f'VM 登录凭据已配置（用户: {vm_config["accountName"]}）'

    return 'missing', 'VM 登录凭据未配置。请在 .privacy-data/privacy-data.json 中设置 kernel_debug_vm'


def main():
    parser = argparse.ArgumentParser(description='双机调试环境检测')
    parser.add_argument('--output', required=True, help='输出 JSON 文件路径')
    parser.add_argument('--vm-name', default=None, help='目标 VM 名称（模糊匹配）')
    args = parser.parse_args()

    checks = []

    # 按依赖顺序检测
    check_fn_list = [
        ('vmrun', check_vmrun),
        ('vm_running', lambda: check_vm_running(args.vm_name)),
        ('kd_exe', check_kd_exe),
        ('vm_debug_config', lambda: check_vm_debug_config(args.vm_name)),
        ('vm_autologin', check_vm_autologin),
    ]

    for name, fn in check_fn_list:
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = 'error', f'检测异常: {e}'
        checks.append({
            'name': name,
            'status': status,
            'detail': detail,
        })

    missing = [c['name'] for c in checks if c['status'] in ('missing', 'error')]
    ready = len(missing) == 0

    result = {
        'ready': ready,
        'checks': checks,
        'missing_items': missing,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 输出摘要到 stdout
    print(f'[{"+" if ready else "-"}] 双机调试环境: {"就绪" if ready else "未就绪"}')
    for c in checks:
        icon = {'ok': '+', 'missing': '-', 'error': '!', 'skip': '?'}.get(c['status'], ' ')
        print(f'  [{icon}] {c["name"]}: {c["detail"]}')

    if missing:
        print(f'\n缺失项: {missing}')
        print('请按 fix_hint 中的指引配置，或参考 $SHARED_DIR/knowledge-base/kernel-driver-analysis.md §1')

    return 0 if ready else 1


if __name__ == '__main__':
    sys.exit(main())
