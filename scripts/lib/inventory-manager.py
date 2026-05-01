#!/usr/bin/env python3
"""
File: scripts/lib/inventory-manager.py
Purpose:
  Manage the homelab Ansible inventory for Taskfile tasks.
Notes:
  - This script may create or update state/ansible/inventory.yml.
  - This script must never create or recreate state/config/.env.
  - This script must never create or recreate passwords.enc.env.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TextIO


def terminal() -> TextIO:
    try:
        return open('/dev/tty', 'r+', encoding='utf-8')
    except OSError:
        return sys.stdin


def prompt_line(handle: TextIO, text: str) -> str:
    output = handle if handle.writable() else sys.stdout
    print(text, end='', file=output, flush=True)
    return handle.readline().strip()


def prompt_required(handle: TextIO, label: str) -> str:
    while True:
        value = prompt_line(handle, f'{label}: ')
        if value:
            return value


def prompt_optional(handle: TextIO, label: str, default: str = '') -> str:
    suffix = f' [{default}]' if default else ''
    value = prompt_line(handle, f'{label}{suffix}: ')
    return value or default


def prompt_count(handle: TextIO) -> int:
    while True:
        value = prompt_optional(handle, 'Number of servers to add', '1')
        if value.isdigit() and int(value) > 0:
            return int(value)
        output = handle if handle.writable() else sys.stdout
        print('Please enter a whole number greater than zero.', file=output)


def env_var_from_hostname(hostname: str) -> str:
    return re.sub(r'[^A-Z0-9_]', '_', f'{hostname}_SSH_PASSWORD'.upper())


def validate_name(label: str, value: str) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
        raise SystemExit(f'ERROR: {label} may only contain letters, numbers, underscore, dot, and dash.')


def validate_env_var(value: str) -> None:
    if value and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise SystemExit('ERROR: SSH password variable must be a valid environment variable name.')


def validate_mac(value: str) -> None:
    if value and not re.fullmatch(r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|[0-9A-Fa-f]{12}', value):
        raise SystemExit('ERROR: MAC address must be blank or a valid 12-digit MAC address.')


def split_suffix(value: str) -> tuple[str, str, str]:
    match = re.match(r'^(.*?)(\d+)([^\d]*)$', value)
    if not match:
        return value, '', ''
    return match.group(1), match.group(2), match.group(3)


def increment_numeric_string(value: str, offset: int) -> str:
    if not value:
        return ''
    if not value.isdigit():
        return value if offset == 0 else ''
    return str(int(value) + offset).zfill(len(value))


def increment_host(value: str, offset: int) -> str:
    prefix, number, suffix = split_suffix(value)
    if not number:
        return value if offset == 0 else f'{value}-{offset + 1}'
    return f'{prefix}{str(int(number) + offset).zfill(len(number))}{suffix}'


def increment_env_var(value: str, offset: int) -> str:
    if not value:
        return ''
    return re.sub(r'[^A-Z0-9_]', '_', increment_host(value, offset).upper())


def increment_mac(value: str, offset: int) -> str:
    if not value:
        return ''
    clean = re.sub(r'[^0-9A-Fa-f]', '', value)
    if len(clean) != 12 or not re.fullmatch(r'[0-9A-Fa-f]{12}', clean):
        return value if offset == 0 else ''
    number = (int(clean, 16) + offset) % (1 << 48)
    hex_value = f'{number:012x}'
    return ':'.join(hex_value[index:index + 2] for index in range(0, 12, 2))


def host_reachable(hostname: str) -> bool:
    lookup = subprocess.run(
        ['getent', 'hosts', hostname],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=1,
    )
    if lookup.returncode != 0:
        return False
    probe = subprocess.run(
        ['ping', '-c', '1', '-W', '1', hostname],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=2,
    )
    return probe.returncode == 0


def scalar(value: str) -> str:
    value = value.strip()
    if value == '':
        return ''
    if value.startswith('{{') and value.endswith('}}'):
        return '"' + value.replace('"', '\\"') + '"'
    if re.fullmatch(r'[A-Za-z0-9_./:@+-]+', value):
        return value
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def parse_inventory(text: str) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, str]]]]:
    root_hosts: dict[str, dict[str, str]] = {}
    groups: dict[str, dict[str, dict[str, str]]] = {}
    current_root_host: str | None = None
    current_group: str | None = None
    current_group_host: str | None = None
    in_root_hosts = False
    in_children = False
    in_group_hosts = False

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith('#'):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(' '))
        stripped = raw_line.strip()
        if ':' not in stripped:
            continue
        key, raw_value = stripped.split(':', 1)
        key = key.strip().strip('"\'')
        value = raw_value.strip().strip('"\'')

        if indent == 0 and key == 'all':
            in_root_hosts = False
            in_children = False
            in_group_hosts = False
            current_root_host = None
            current_group = None
            current_group_host = None
            continue
        if indent == 2 and key == 'hosts':
            in_root_hosts = True
            in_children = False
            in_group_hosts = False
            current_root_host = None
            continue
        if indent == 2 and key == 'children':
            in_root_hosts = False
            in_children = True
            in_group_hosts = False
            current_group = None
            current_group_host = None
            continue
        if in_root_hosts and indent == 4 and value == '':
            current_root_host = key
            root_hosts.setdefault(current_root_host, {})
            continue
        if in_root_hosts and indent == 6 and current_root_host:
            root_hosts[current_root_host][key] = value
            continue
        if in_children and indent == 4 and value == '':
            current_group = key
            groups.setdefault(current_group, {})
            in_group_hosts = False
            current_group_host = None
            continue
        if in_children and current_group and indent == 6 and key == 'hosts':
            in_group_hosts = True
            current_group_host = None
            continue
        if in_children and current_group and in_group_hosts and indent == 8 and value == '':
            current_group_host = key
            groups.setdefault(current_group, {}).setdefault(current_group_host, {})
            continue
        if in_children and current_group and current_group_host and indent == 10:
            groups[current_group][current_group_host][key] = value
            continue
    return root_hosts, groups


def write_inventory(inventory_file: Path, root_hosts: dict[str, dict[str, str]], groups: dict[str, dict[str, dict[str, str]]]) -> None:
    lines: list[str] = ['all:', '  hosts:']
    for host_name in sorted(root_hosts):
        lines.append(f'    {host_name}:')
        for key, value in root_hosts[host_name].items():
            lines.append(f'      {key}: {scalar(value)}')
    if groups:
        lines.append('  children:')
        for group_name in sorted(groups):
            lines.append(f'    {group_name}:')
            lines.append('      hosts:')
            for host_name in sorted(groups[group_name]):
                lines.append(f'        {host_name}:')
                for key, value in groups[group_name][host_name].items():
                    lines.append(f'          {key}: {scalar(value)}')
    else:
        lines.append('  children: {}')
    inventory_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.chmod(inventory_file, 0o600)


def read_inventory(inventory_file: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, str]]]]:
    existing_text = inventory_file.read_text(encoding='utf-8') if inventory_file.exists() else ''
    root_hosts, groups = parse_inventory(existing_text)
    if not root_hosts:
        root_hosts['local'] = {
            'ansible_host': '127.0.0.1',
            'ansible_connection': 'local',
            'ansible_user': os.environ.get('USER', 'root'),
            'ansible_port': '22',
            'ansible_python_interpreter': 'auto_silent',
        }
    return root_hosts, groups


def add_servers(args: argparse.Namespace, interactive: bool) -> None:
    inventory_file = Path(args.inventory_file)
    password_file = args.password_file

    if interactive:
        tty = terminal()
        group = prompt_required(tty, 'Group')
        server_count = prompt_count(tty)
        first_vm_lxc_id = prompt_optional(tty, 'First VM/LXC container ID (blank for physical servers and routers)')
        first_hostname = prompt_required(tty, 'First hostname')
        first_mac_address = prompt_optional(tty, 'First MAC address')
        ssh_user = prompt_required(tty, 'SSH username')
        default_password_var = env_var_from_hostname(first_hostname)
        first_ssh_password_var = prompt_optional(tty, f'SSH password variable in {password_file}', default_password_var)
        python_interpreter = prompt_optional(tty, 'Python interpreter', 'auto_silent')
        check_network = True
    else:
        group = args.group
        server_count = 1
        first_vm_lxc_id = args.vm_lxc_id or ''
        first_hostname = args.hostname
        first_mac_address = args.mac_address or ''
        ssh_user = args.ssh_user
        first_ssh_password_var = args.ssh_password_var or ''
        python_interpreter = args.python_interpreter or 'auto_silent'
        check_network = False

    validate_name('Group', group)
    validate_name('Hostname', first_hostname)
    validate_env_var(first_ssh_password_var)
    validate_mac(first_mac_address)

    root_hosts, groups = read_inventory(inventory_file)
    all_inventory_hosts = set(root_hosts)
    for group_hosts in groups.values():
        all_inventory_hosts.update(group_hosts)

    report: list[tuple[str, str, str]] = []
    added = 0
    groups.setdefault(group, {})

    for offset in range(server_count):
        hostname = increment_host(first_hostname, offset)
        vm_lxc_id = increment_numeric_string(first_vm_lxc_id, offset)
        mac_address = increment_mac(first_mac_address, offset)
        ssh_password_var = increment_env_var(first_ssh_password_var, offset)

        if hostname in all_inventory_hosts:
            report.append(('SKIPPED', hostname, 'already exists in inventory'))
            continue
        if check_network and host_reachable(hostname):
            report.append(('SKIPPED', hostname, 'hostname resolves and responds on the network'))
            continue

        server = {
            'ansible_host': hostname,
            'ansible_user': ssh_user,
            'ansible_port': '22',
            'ansible_python_interpreter': python_interpreter,
        }
        if vm_lxc_id:
            server['homelab_vm_lxc_id'] = vm_lxc_id
        if mac_address:
            server['homelab_mac_address'] = mac_address
        if ssh_password_var:
            server['ansible_password'] = "{{ lookup('env', '" + ssh_password_var + "') }}"
            server['homelab_ssh_password_var'] = ssh_password_var

        groups[group][hostname] = server
        all_inventory_hosts.add(hostname)
        added += 1
        report.append(('ADDED', hostname, f'group={group}, vm_lxc_id={vm_lxc_id or "-"}, mac={mac_address or "-"}, password_var={ssh_password_var or "-"}'))

    if added:
        write_inventory(inventory_file, root_hosts, groups)

    print('\nInventory add report')
    print('--------------------')
    for status, hostname, detail in report:
        print(f'{status:7} {hostname:30} {detail}')
    print(f'\nInventory file: {inventory_file}')
    print(f'Password file reference only: {password_file}')
    print(f'Servers requested: {server_count}; added: {added}; skipped: {server_count - added}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Manage homelab Ansible inventory entries.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    interactive_parser = subparsers.add_parser('interactive-add')
    interactive_parser.add_argument('--inventory-file', required=True)
    interactive_parser.add_argument('--password-file', required=True)

    add_parser = subparsers.add_parser('add-server')
    add_parser.add_argument('--inventory-file', required=True)
    add_parser.add_argument('--password-file', required=True)
    add_parser.add_argument('--group', required=True)
    add_parser.add_argument('--hostname', required=True)
    add_parser.add_argument('--ssh-user', required=True)
    add_parser.add_argument('--vm-lxc-id', default='')
    add_parser.add_argument('--mac-address', default='')
    add_parser.add_argument('--ssh-password-var', default='')
    add_parser.add_argument('--python-interpreter', default='auto_silent')

    args = parser.parse_args()
    if args.command == 'interactive-add':
        add_servers(args, interactive=True)
        return 0
    if args.command == 'add-server':
        add_servers(args, interactive=False)
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
