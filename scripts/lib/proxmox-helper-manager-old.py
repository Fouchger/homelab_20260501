#!/usr/bin/env python3
"""
File: scripts/lib/proxmox-helper-manager.py
Purpose:
  Reusable wrapper for Proxmox Community Scripts LXC installers.
Notes:
  - Stores confirmed per-script variables in state/proxmox_helper_scripts/<script>.conf.
  - Does not create or recreate state/config/.env.
  - Does not create or recreate state/secrets/passwords/passwords.enc.env.
  - Adds created LXCs to inventory only by calling the existing inventory manager.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import TextIO

CATALOG: dict[str, dict[str, str]] = {
    'plex': {'title': 'Plex Media Server LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/plex.sh', 'tags': 'media;plex;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'yes'},
    'technitiumdns': {'title': 'Technitium DNS LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/technitiumdns.sh', 'tags': 'dns;technitium;automated', 'cpu': '2', 'ram': '1024', 'disk': '4', 'gpu': 'no'},
    'sonarr': {'title': 'Sonarr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/sonarr.sh', 'tags': 'media;arr;sonarr;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'no'},
    'radarr': {'title': 'Radarr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/radarr.sh', 'tags': 'media;arr;radarr;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'no'},
    'lidarr': {'title': 'Lidarr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/lidarr.sh', 'tags': 'media;arr;lidarr;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'no'},
    'readarr': {'title': 'Readarr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/readarr.sh', 'tags': 'media;arr;readarr;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'no'},
    'prowlarr': {'title': 'Prowlarr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/prowlarr.sh', 'tags': 'media;arr;prowlarr;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'no'},
    'whisparr': {'title': 'Whisparr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/whisparr.sh', 'tags': 'media;arr;whisparr;automated', 'cpu': '2', 'ram': '2048', 'disk': '8', 'gpu': 'no'},
    'bazarr': {'title': 'Bazarr LXC', 'url': 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/bazarr.sh', 'tags': 'media;arr;bazarr;automated', 'cpu': '2', 'ram': '1024', 'disk': '4', 'gpu': 'no'},
}

ORDER = [
    'script', 'title', 'url', 'target', 'inventory_group', 'count', 'hostname_prefix', 'start_hostname_index',
    'start_vmid', 'ansible_host_mode', 'start_ip_cidr', 'gateway', 'dns_server', 'bridge', 'vlan', 'mac',
    'ssh_user', 'inject_control_plane_key', 'ssh_public_key_file', 'root_password_var', 'root_password_value',
    'os', 'version', 'unprivileged', 'cpu', 'ram', 'disk', 'container_storage', 'template_storage',
    'ipv6_method', 'mtu', 'search_domain', 'tags', 'ssh', 'fuse', 'tun', 'nesting', 'gpu', 'keyctl',
    'apt_cacher', 'apt_cacher_ip', 'timezone', 'protection', 'mknod', 'mount_fs', 'start_after_create',
    'start_on_boot', 'verbose', 'add_to_inventory', 'python_interpreter', 'normalise_auth_after_create'
]


def terminal() -> TextIO:
    try:
        return open('/dev/tty', 'r+', encoding='utf-8')
    except OSError:
        return sys.stdin


def prompt(handle: TextIO, label: str, default: str = '') -> str:
    out = handle if handle.writable() else sys.stdout
    suffix = f' [{default}]' if default else ''
    print(f'{label}{suffix}: ', end='', file=out, flush=True)
    value = handle.readline().strip()
    return value if value else default


def read_conf(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        data[key.strip()] = shlex.split(value, posix=True)[0] if value.strip() else ''
    return data


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def write_conf(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '# Homelab Proxmox Community Script configuration',
        '# Created and maintained by scripts/lib/proxmox-helper-manager.py',
        '# Values are shell-style KEY=VALUE pairs.',
        '',
    ]
    for key in ORDER:
        if key in data:
            lines.append(f'{key}={shell_quote(data.get(key, ""))}')
    for key in sorted(set(data) - set(ORDER)):
        lines.append(f'{key}={shell_quote(data.get(key, ""))}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.chmod(path, 0o600)


def config_path(state_dir: Path, script: str) -> Path:
    return state_dir / f'{script}.conf'


def default_config(script: str, state_dir: Path, ssh_key_file: str) -> dict[str, str]:
    if script not in CATALOG:
        raise SystemExit(f'ERROR: Unsupported script: {script}')
    app = CATALOG[script]
    return {
        'script': script,
        'title': app['title'],
        'url': app['url'],
        'target': 'proxmox',
        'inventory_group': script,
        'count': '1',
        'hostname_prefix': script.replace('technitiumdns', 'dns'),
        'start_hostname_index': '1',
        'start_vmid': '',
        'ansible_host_mode': 'dhcp',
        'start_ip_cidr': '',
        'gateway': '',
        'dns_server': '',
        'bridge': 'vmbr0',
        'vlan': '',
        'mac': '',
        'ssh_user': 'root',
        'inject_control_plane_key': 'yes',
        'ssh_public_key_file': f'{ssh_key_file}.pub',
        'root_password_var': '',
        'root_password_value': '',
        'os': 'ubuntu',
        'version': '24.04',
        'unprivileged': '1',
        'cpu': app['cpu'],
        'ram': app['ram'],
        'disk': app['disk'],
        'container_storage': 'local-lvm',
        'template_storage': 'local-lvm',
        'ipv6_method': 'none',
        'mtu': '',
        'search_domain': '',
        'tags': app['tags'],
        'ssh': 'yes',
        'fuse': 'no',
        'tun': 'no',
        'nesting': '1',
        'gpu': app['gpu'],
        'keyctl': '0',
        'apt_cacher': 'no',
        'apt_cacher_ip': '',
        'timezone': '',
        'protection': 'no',
        'mknod': '0',
        'mount_fs': '',
        'start_after_create': '1',
        'start_on_boot': '1',
        'verbose': 'no',
        'add_to_inventory': 'yes',
        'python_interpreter': 'auto_silent',
        'normalise_auth_after_create': 'yes',
    }


def candidate_executable_paths(command_name: str) -> list[Path]:
    candidates: list[Path] = []
    for path_entry in os.environ.get('PATH', '').split(os.pathsep):
        if path_entry:
            candidates.append(Path(path_entry) / command_name)
    candidates.append(Path.home() / '.local' / 'bin' / command_name)
    candidates.append(Path('/usr/local/bin') / command_name)
    candidates.append(Path('/usr/bin') / command_name)
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_executable(command_name: str) -> str | None:
    for candidate in candidate_executable_paths(command_name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def require_executable(command_name: str) -> str:
    executable = resolve_executable(command_name)
    if executable:
        return executable
    raise SystemExit(
        f'ERROR: Required command not found: {command_name}\n'
        f'Checked PATH plus {Path.home() / ".local" / "bin"}.\n'
        'If this is a pipx-installed command, run: task apps:ansible'
    )


def normalise_script(script: str) -> str:
    script = script.strip().lower()
    if script not in CATALOG:
        raise SystemExit(f'ERROR: Unsupported script "{script}". Run list to see supported scripts.')
    return script


def cmd_list(_: argparse.Namespace) -> int:
    print('Supported Proxmox Community Scripts')
    print('-----------------------------------')
    for key, meta in CATALOG.items():
        print(f'{key:14} {meta["title"]}')
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    script = normalise_script(args.script)
    path = config_path(Path(args.state_dir), script)
    if path.exists() and not args.force:
        print(f'Config already exists: {path}')
        return 0
    write_conf(path, default_config(script, Path(args.state_dir), args.ssh_key_file))
    print(f'Config written: {path}')
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    script = normalise_script(args.script)
    state_dir = Path(args.state_dir)
    path = config_path(state_dir, script)
    data = default_config(script, state_dir, args.ssh_key_file)
    data.update(read_conf(path))
    tty = terminal()
    print(f'Configure {script} - {data["title"]}', file=(tty if tty.writable() else sys.stdout))
    print('Leave a value blank to keep the current default. These prompts mirror the upstream Advanced Install variable model.\n', file=(tty if tty.writable() else sys.stdout))

    # Homelab orchestration fields.
    data['target'] = prompt(tty, 'Target Proxmox host/group', data['target'])
    data['inventory_group'] = prompt(tty, 'Inventory group for created LXCs', data['inventory_group'])
    data['count'] = prompt(tty, 'Number of LXCs to create', data['count'])
    data['hostname_prefix'] = prompt(tty, 'Hostname prefix', data['hostname_prefix'])
    data['start_hostname_index'] = prompt(tty, 'Start hostname index', data['start_hostname_index'])

    # Upstream advanced sequence.
    data['unprivileged'] = prompt(tty, 'Step 1 - Container type: unprivileged 1 or privileged 0', data['unprivileged'])
    data['root_password_var'] = prompt(tty, 'Step 2 - Root password variable name (blank for no upstream root password)', data['root_password_var'])
    data['start_vmid'] = prompt(tty, 'Step 3 - Start VMID / CTID (blank to let upstream choose)', data['start_vmid'])
    data['disk'] = prompt(tty, 'Step 5 - Disk size in GB', data['disk'])
    data['cpu'] = prompt(tty, 'Step 6 - CPU cores', data['cpu'])
    data['ram'] = prompt(tty, 'Step 7 - RAM in MiB', data['ram'])
    data['bridge'] = prompt(tty, 'Step 8 - Network bridge', data['bridge'])
    data['ansible_host_mode'] = prompt(tty, 'Step 9 - IPv4 mode: dhcp, static, or range', data['ansible_host_mode'])
    data['start_ip_cidr'] = prompt(tty, 'Step 9 - First static IPv4 CIDR (blank for DHCP/range)', data['start_ip_cidr'])
    data['gateway'] = prompt(tty, 'Step 9 - Gateway IP (required for static)', data['gateway'])
    data['ipv6_method'] = prompt(tty, 'Step 10 - IPv6 method: auto, dhcp, static, none', data['ipv6_method'])
    data['mtu'] = prompt(tty, 'Step 11 - MTU size (blank for default)', data['mtu'])
    data['search_domain'] = prompt(tty, 'Step 12 - DNS search domain', data['search_domain'])
    data['dns_server'] = prompt(tty, 'Step 13 - DNS server', data['dns_server'])
    data['mac'] = prompt(tty, 'Step 14 - MAC address for first LXC (blank for generated)', data['mac'])
    data['vlan'] = prompt(tty, 'Step 15 - VLAN tag', data['vlan'])
    data['tags'] = prompt(tty, 'Step 16 - Tags', data['tags'])
    data['ssh'] = prompt(tty, 'Step 17 - Enable SSH in container (yes/no)', data['ssh'])
    data['inject_control_plane_key'] = prompt(tty, 'Step 17 - Inject control-plane SSH public key (yes/no)', data['inject_control_plane_key'])
    data['ssh_public_key_file'] = prompt(tty, 'Step 17 - SSH public key file to inject', data['ssh_public_key_file'])
    data['fuse'] = prompt(tty, 'Step 18 - Enable FUSE support (yes/no)', data['fuse'])
    data['tun'] = prompt(tty, 'Step 19 - Enable TUN/TAP support (yes/no)', data['tun'])
    data['nesting'] = prompt(tty, 'Step 20 - Enable nesting (1/0)', data['nesting'])
    data['gpu'] = prompt(tty, 'Step 21 - Enable GPU passthrough (yes/no)', data['gpu'])
    data['keyctl'] = prompt(tty, 'Step 22 - Enable keyctl (1/0)', data['keyctl'])
    data['apt_cacher'] = prompt(tty, 'Step 23 - Use APT Cacher-NG proxy (yes/no)', data['apt_cacher'])
    data['apt_cacher_ip'] = prompt(tty, 'Step 23 - APT Cacher-NG IP or URL', data['apt_cacher_ip'])
    data['timezone'] = prompt(tty, 'Step 24 - Container timezone (blank for host)', data['timezone'])
    data['protection'] = prompt(tty, 'Step 25 - Container protection (yes/no)', data['protection'])
    data['mknod'] = prompt(tty, 'Step 26 - Allow mknod (1/0)', data['mknod'])
    data['mount_fs'] = prompt(tty, 'Step 27 - Allowed mount filesystems', data['mount_fs'])
    data['verbose'] = prompt(tty, 'Step 28 - Verbose upstream output (yes/no)', data['verbose'])

    # Homelab post-create behaviour.
    data['container_storage'] = prompt(tty, 'Container root filesystem storage', data['container_storage'])
    data['template_storage'] = prompt(tty, 'Template storage', data['template_storage'])
    data['start_after_create'] = prompt(tty, 'Start after create (1/0)', data['start_after_create'])
    data['start_on_boot'] = prompt(tty, 'Start on boot (1/0)', data['start_on_boot'])
    data['ssh_user'] = prompt(tty, 'Inventory SSH username for created LXCs', data['ssh_user'])
    data['add_to_inventory'] = prompt(tty, 'Add created LXCs to Ansible inventory after successful create (yes/no)', data['add_to_inventory'])
    data['python_interpreter'] = prompt(tty, 'Inventory Python interpreter', data['python_interpreter'])
    data['normalise_auth_after_create'] = prompt(tty, 'Normalise created inventory entries to key-based auth (yes/no)', data['normalise_auth_after_create'])

    validate_config(data)
    write_conf(path, data)
    print(f'Config written: {path}')
    return 0


def validate_config(data: dict[str, str]) -> None:
    if not data.get('target'):
        raise SystemExit('ERROR: target is required.')
    if not data.get('inventory_group'):
        raise SystemExit('ERROR: inventory_group is required.')
    if not data.get('count', '').isdigit() or int(data['count']) < 1:
        raise SystemExit('ERROR: count must be a whole number greater than zero.')
    if not data.get('hostname_prefix'):
        raise SystemExit('ERROR: hostname_prefix is required.')
    if data.get('ansible_host_mode') == 'static' and not data.get('start_ip_cidr'):
        raise SystemExit('ERROR: start_ip_cidr is required for static IPv4 mode.')
    if data.get('start_ip_cidr'):
        ipaddress.ip_interface(data['start_ip_cidr'])
    if data.get('mac') and not re.fullmatch(r'([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', data['mac']):
        raise SystemExit('ERROR: mac must be blank or use format XX:XX:XX:XX:XX:XX.')


def increment_hostname(prefix: str, start_index: str, offset: int) -> str:
    index = int(start_index or '1') + offset
    width = max(2, len(start_index or '1'))
    return f'{prefix}{index:0{width}d}'


def increment_vmid(start_vmid: str, offset: int) -> str:
    return str(int(start_vmid) + offset) if start_vmid else ''


def increment_mac(mac: str, offset: int) -> str:
    if not mac:
        return ''
    number = int(mac.replace(':', ''), 16) + offset
    hex_value = f'{number % (1 << 48):012x}'
    return ':'.join(hex_value[i:i+2] for i in range(0, 12, 2))


def increment_ip_cidr(cidr: str, offset: int) -> str:
    if not cidr:
        return ''
    interface = ipaddress.ip_interface(cidr)
    next_ip = interface.ip + offset
    return f'{next_ip}/{interface.network.prefixlen}'


def host_ip_from_cidr(cidr: str) -> str:
    return str(ipaddress.ip_interface(cidr).ip) if cidr else ''


def build_runs(data: dict[str, str]) -> list[dict[str, str]]:
    validate_config(data)
    runs: list[dict[str, str]] = []
    for offset in range(int(data['count'])):
        hostname = increment_hostname(data['hostname_prefix'], data.get('start_hostname_index', '1'), offset)
        vmid = increment_vmid(data.get('start_vmid', ''), offset)
        ip_cidr = increment_ip_cidr(data.get('start_ip_cidr', ''), offset)
        mac = increment_mac(data.get('mac', ''), offset)
        ansible_host = host_ip_from_cidr(ip_cidr) if data.get('ansible_host_mode') == 'static' else hostname
        runs.append({'hostname': hostname, 'vmid': vmid, 'ip_cidr': ip_cidr, 'ansible_host': ansible_host, 'mac': mac})
    return runs


def env_for_run(data: dict[str, str], run: dict[str, str]) -> dict[str, str]:
    env = {
        'var_unprivileged': data['unprivileged'],
        'var_ctid': run['vmid'],
        'var_hostname': run['hostname'],
        'var_cpu': data['cpu'],
        'var_ram': data['ram'],
        'var_disk': data['disk'],
        'var_brg': data['bridge'],
        'var_net': run['ip_cidr'] if data.get('ansible_host_mode') == 'static' else data.get('ansible_host_mode', 'dhcp'),
        'var_gateway': data.get('gateway', ''),
        'var_ipv6_method': data.get('ipv6_method', 'none'),
        'var_mtu': data.get('mtu', ''),
        'var_searchdomain': data.get('search_domain', ''),
        'var_ns': data.get('dns_server', ''),
        'var_mac': run['mac'],
        'var_vlan': data.get('vlan', ''),
        'var_tags': data.get('tags', ''),
        'var_ssh': data.get('ssh', 'yes'),
        'var_fuse': data.get('fuse', 'no'),
        'var_tun': data.get('tun', 'no'),
        'var_nesting': data.get('nesting', '1'),
        'var_gpu': data.get('gpu', 'no'),
        'var_keyctl': data.get('keyctl', '0'),
        'var_apt_cacher': data.get('apt_cacher', 'no'),
        'var_apt_cacher_ip': data.get('apt_cacher_ip', ''),
        'var_timezone': data.get('timezone', ''),
        'var_protection': data.get('protection', 'no'),
        'var_mknod': data.get('mknod', '0'),
        'var_mount_fs': data.get('mount_fs', ''),
        'var_verbose': data.get('verbose', 'no'),
        'var_container_storage': data.get('container_storage', ''),
        'var_template_storage': data.get('template_storage', ''),
        'var_os': data.get('os', 'ubuntu'),
        'var_version': data.get('version', '24.04'),
    }
    if data.get('inject_control_plane_key', 'yes').lower() in {'1', 'yes', 'true'}:
        key_file = Path(data.get('ssh_public_key_file', '')).expanduser()
        if key_file.is_file():
            env['var_ssh_authorized_key'] = key_file.read_text(encoding='utf-8').strip()
        else:
            print(f'WARNING: SSH public key file not found, key will not be injected: {key_file}', file=sys.stderr)
    if data.get('root_password_value'):
        env['var_pw'] = data['root_password_value']
    return {key: value for key, value in env.items() if value != ''}


def remote_command(data: dict[str, str], run: dict[str, str]) -> str:
    assignments = ' '.join(f'{key}={shlex.quote(value)}' for key, value in env_for_run(data, run).items())
    return f'{assignments} bash -c "$(curl -fsSL {shlex.quote(data["url"])})" default'


def load_required_config(args: argparse.Namespace) -> tuple[Path, dict[str, str]]:
    script = normalise_script(args.script)
    path = config_path(Path(args.state_dir), script)
    if not path.exists():
        raise SystemExit(f'ERROR: Missing config: {path}\nRun: task proxmox_scripts:community:init SCRIPT={script}')
    data = default_config(script, Path(args.state_dir), args.ssh_key_file)
    data.update(read_conf(path))
    return path, data


def cmd_plan(args: argparse.Namespace) -> int:
    path, data = load_required_config(args)
    print(f'Proxmox Community Script plan: {data["script"]}')
    print('--------------------------------------------')
    print(f'Config: {path}')
    print(f'Target: {data["target"]}')
    print(f'Inventory group after create: {data["inventory_group"]}')
    print(f'Upstream URL: {data["url"]}')
    print('')
    for run in build_runs(data):
        print(f'- {run["hostname"]}: vmid={run["vmid"] or "auto"}, ansible_host={run["ansible_host"]}, ip_cidr={run["ip_cidr"] or data.get("ansible_host_mode", "dhcp")}, mac={run["mac"] or "auto"}')
    print('\nDry-run by default. Use EXECUTE=yes on the Taskfile run task to create LXCs.')
    return 0


def run_ansible(inventory_file: str, target: str, command: str) -> int:
    ansible = require_executable('ansible')
    cmd = [ansible, target, '-i', inventory_file, '-m', 'shell', '-a', command]
    env = os.environ.copy()
    env['PATH'] = f'{Path.home() / ".local" / "bin"}{os.pathsep}' + env.get('PATH', '')
    return subprocess.run(cmd, check=False, env=env).returncode


def add_inventory_entry(args: argparse.Namespace, data: dict[str, str], run: dict[str, str]) -> int:
    command = [
        sys.executable, '-S', args.inventory_manager_script, 'add-server',
        '--inventory-file', args.inventory_file,
        '--password-file', args.password_file,
        '--recipients-file', args.recipients_file,
        '--group', data['inventory_group'],
        '--hostname', run['hostname'],
        '--ansible-host', run['ansible_host'],
        '--ssh-user', data.get('ssh_user', 'root'),
        '--vm-lxc-id', run['vmid'],
        '--mac-address', run['mac'],
        '--python-interpreter', data.get('python_interpreter', 'auto_silent'),
    ]
    return subprocess.run(command, check=False).returncode


def normalise_inventory(args: argparse.Namespace) -> int:
    command = [sys.executable, '-S', args.inventory_manager_script, 'normalise-auth', '--inventory-file', args.inventory_file, '--ssh-key-file', args.ssh_key_file]
    return subprocess.run(command, check=False).returncode


def cmd_run(args: argparse.Namespace) -> int:
    path, data = load_required_config(args)
    execute = args.execute.lower() in {'1', 'yes', 'true'}
    if not execute:
        print('Dry-run only. Planned commands:')
        for run in build_runs(data):
            print(f'\n# {run["hostname"]}')
            print(remote_command(data, run))
        print('\nRun with EXECUTE=yes to create LXCs.')
        return 0

    ansible_path = require_executable('ansible')
    print(f'Using Ansible: {ansible_path}')

    failures = 0
    added = 0
    for run in build_runs(data):
        print(f'\nCreating {run["hostname"]} on target {data["target"]}')
        rc = run_ansible(args.inventory_file, data['target'], remote_command(data, run))
        if rc != 0:
            print(f'ERROR: Upstream create failed for {run["hostname"]} with exit code {rc}', file=sys.stderr)
            failures += 1
            continue
        if data.get('add_to_inventory', 'yes').lower() in {'1', 'yes', 'true'}:
            rc = add_inventory_entry(args, data, run)
            if rc == 0:
                added += 1
            else:
                print(f'ERROR: Failed to add {run["hostname"]} to inventory.', file=sys.stderr)
                failures += 1
    if added and data.get('normalise_auth_after_create', 'yes').lower() in {'1', 'yes', 'true'}:
        normalise_inventory(args)
    print('\nProxmox Community Script run report')
    print('-----------------------------------')
    print(f'Config: {path}')
    print(f'Requested: {len(build_runs(data))}; inventory_added_or_updated: {added}; failures: {failures}')
    return 1 if failures else 0


def cmd_audit(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    print('Proxmox Community Script configs')
    print('--------------------------------')
    for script in CATALOG:
        path = config_path(state_dir, script)
        if path.exists():
            data = read_conf(path)
            print(f'[OK]       {script:14} {path} target={data.get("target", "-")} count={data.get("count", "-")}')
        else:
            print(f'[OPTIONAL] {script:14} not configured')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Manage Proxmox Community Script configs and runs.')
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--inventory-file', required=True)
    parser.add_argument('--inventory-manager-script', required=True)
    parser.add_argument('--password-file', required=True)
    parser.add_argument('--recipients-file', required=True)
    parser.add_argument('--ssh-key-file', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    init = sub.add_parser('init')
    init.add_argument('--script', required=True)
    init.add_argument('--force', action='store_true')
    conf = sub.add_parser('configure')
    conf.add_argument('--script', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--script', required=True)
    run = sub.add_parser('run')
    run.add_argument('--script', required=True)
    run.add_argument('--execute', default='no')
    sub.add_parser('audit')
    args = parser.parse_args()
    if args.command == 'list':
        return cmd_list(args)
    if args.command == 'init':
        return cmd_init(args)
    if args.command == 'configure':
        return cmd_configure(args)
    if args.command == 'plan':
        return cmd_plan(args)
    if args.command == 'run':
        return cmd_run(args)
    if args.command == 'audit':
        return cmd_audit(args)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
