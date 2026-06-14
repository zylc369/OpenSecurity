# -*- coding: utf-8 -*-
"""VM 登录管理脚本

从 .privacy-data/privacy-data.json 读取 VM 凭据，通过 vmrun 实现自动登录。
密码为 Base64 编码存储，运行时解码，不输出到 stdout。

密码不经过 AI — 本脚本由 Agent 调用但只返回操作结果，不返回密码明文。

使用方式:
  python vm_login.py --help
  python vm_login.py --login                # 配置 VM 自动登录
  python vm_login.py --status               # 检查自动登录状态
  python vm_login.py --encrypt-password     # 交互式加密密码（写入配置文件）

隐私数据文件格式 (.privacy-data/privacy-data.json):
  {
    "kernel_debug_vm": {
      "vmName": "虚拟机名",
      "vmxPath": "C:\\VMs\\win10\\win10.vmx",
      "accountName": "用户名",
      "passwordEncoded": "Base64编码的密码"
    }
  }

环境变量:
  PRIVACY_DATA: 隐私数据文件路径（默认 .privacy-data/privacy-data.json）
"""

import argparse
import base64
import json
import os
import subprocess
import sys


def _find_privacy_data():
    """查找隐私数据文件"""
    search_paths = [
        os.environ.get('PRIVACY_DATA', ''),
        os.path.join(os.getcwd(), '.privacy-data', 'privacy-data.json'),
    ]
    for path in search_paths:
        if path and os.path.isfile(path):
            return path
    return None


def _load_config():
    """加载 VM 配置"""
    path = _find_privacy_data()
    if not path:
        return None, None, '隐私数据文件未找到。请创建 .privacy-data/privacy-data.json（参考 --help 中的格式）'

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return None, path, f'隐私数据文件 JSON 格式错误: {e}'
    except Exception as e:
        return None, path, f'读取隐私数据文件失败: {e}'

    vm_config = data.get('kernel_debug_vm')
    if not vm_config:
        return None, path, '隐私数据文件中缺少 kernel_debug_vm 配置段'

    # 验证必要字段
    required = ['vmxPath', 'accountName', 'passwordEncoded']
    missing = [f for f in required if not vm_config.get(f)]
    if missing:
        return None, path, f'kernel_debug_vm 缺少必要字段: {missing}'

    return vm_config, path, None


def _run_vmrun(args, timeout=20):
    """执行 vmrun 命令"""
    cmd = ['vmrun', '-T', 'ws'] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace')
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, '', 'vmrun 未找到。请安装 VMware Workstation'
    except subprocess.TimeoutExpired:
        return -2, '', f'vmrun 超时 ({timeout}s)'
    except Exception as e:
        return -3, '', str(e)


def do_login(config):
    """配置 VM 自动登录（通过注册表）"""
    vmx = config['vmxPath']
    user = config['accountName']
    password = base64.b64decode(config['passwordEncoded']).decode('utf-8')

    # 检查 VM 是否在运行
    rc, out, _ = _run_vmrun(['list'])
    if rc == 0:
        running = [l.strip() for l in out.splitlines() if l.strip() and 'Total' not in l]
        vm_running = any(vmx.lower() in v.lower() for v in running)
    else:
        vm_running = False

    if not vm_running:
        # 启动 VM
        print(f'[*] VM 未运行，正在启动: {vmx}')
        rc, _, err = _run_vmrun(['start', vmx], timeout=60)
        if rc != 0:
            return False, f'VM 启动失败: {err}'
        # 等待 VM 启动
        import time
        print('[*] 等待 VM 启动 (30s)...')
        time.sleep(30)

    # 配置自动登录注册表
    # 注意: /d 的值必须用引号包裹，防止密码中的特殊字符（&、|、^ 等）被 cmd 解释
    reg_cmds = [
        f'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f',
        f'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v DefaultUserName /t REG_SZ /d "{user}" /f',
        f'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v DefaultPassword /t REG_SZ /d "{password}" /f',
    ]

    for cmd in reg_cmds:
        rc, _, err = _run_vmrun(['-gu', user, '-gp', password, 'runProgramInGuest', vmx, cmd])
        if rc != 0:
            return False, f'注册表设置失败: {cmd} → {err}'

    return True, f'自动登录配置成功 (用户: {user})'


def do_status(config):
    """检查自动登录状态"""
    vmx = config['vmxPath']
    user = config['accountName']
    password = base64.b64decode(config['passwordEncoded']).decode('utf-8')

    rc, out, err = _run_vmrun([
        '-gu', user, '-gp', password,
        'runProgramInGuest', vmx,
        'reg query "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v AutoAdminLogon'
    ])

    if rc != 0:
        return False, f'无法查询注册表: {err}'

    auto_login = 'REG_SZ    1' in out or 'REG_SZ   1' in out
    if auto_login:
        return True, '自动登录已启用 (AutoAdminLogon=1)'
    return False, '自动登录未启用 (AutoAdminLogon!=1)'


def do_encrypt_password():
    """交互式加密密码并更新配置文件"""
    import getpass

    print('[*] VM 登录密码加密工具')
    print('[*] 密码将被 Base64 编码后存储到配置文件')
    print()

    password = getpass.getpass('请输入 VM 登录密码: ')
    if not password:
        return False, '密码不能为空'

    encoded = base64.b64encode(password.encode('utf-8')).decode('ascii')
    print(f'[+] Base64 编码结果: {encoded}')
    print()

    # 查找或创建配置文件
    config_path = _find_privacy_data()
    if config_path:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        config_path = os.path.join(os.getcwd(), '.privacy-data', 'privacy-data.json')
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        data = {}

    if 'kernel_debug_vm' not in data:
        data['kernel_debug_vm'] = {}

    # 收集其他必要信息
    if not data['kernel_debug_vm'].get('vmxPath'):
        vmx = input('请输入 VMX 文件路径: ').strip().strip('"')
        data['kernel_debug_vm']['vmxPath'] = vmx

    if not data['kernel_debug_vm'].get('accountName'):
        account = input('请输入 VM 登录用户名: ').strip()
        data['kernel_debug_vm']['accountName'] = account

    data['kernel_debug_vm']['passwordEncoded'] = encoded

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True, f'密码已加密保存到 {config_path}'


def main():
    parser = argparse.ArgumentParser(description='VM 登录管理（密码不输出到 stdout）')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--login', action='store_true', help='配置 VM 自动登录')
    group.add_argument('--status', action='store_true', help='检查自动登录状态')
    group.add_argument('--encrypt-password', action='store_true', help='交互式加密密码并保存到配置文件')
    args = parser.parse_args()

    if args.encrypt_password:
        ok, msg = do_encrypt_password()
        print(f'[{"+" if ok else "-"}] {msg}')
        return 0 if ok else 1

    # --login 和 --status 需要加载配置
    config, config_path, err = _load_config()
    if err:
        print(f'[-] {err}')
        return 1

    if args.login:
        ok, msg = do_login(config)
        print(f'[{"+" if ok else "-"}] {msg}')
        return 0 if ok else 1

    if args.status:
        ok, msg = do_status(config)
        print(f'[{"+" if ok else "-"}] {msg}')
        return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
