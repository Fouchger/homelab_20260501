#!/usr/bin/env python3
"""
File: scripts/lib/inventory-network-sync.py
Purpose:
  Update the homelab Ansible inventory from arp-scan output.
Notes:
  - Existing host entries are preserved and updated by ansible_host or MAC match.
  - New discovered host entries use the same core fields as inventory-manager.py.
  - This script does not create or update any password files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any


def load_inventory_manager() -> Any:
    manager_path = Path(__file__).with_name('inventory-manager.py')
    spec = importlib.util.spec_from_file_location('inventory_manager', manager_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f'ERROR: Unable to load inventory manager from {manager_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY_MANAGER = load_inventory_manager()


def normalise_mac(value: str) -> str:
    clean = re.sub(r'[^0-9A-Fa-f]', '', value or '')
    if len(clean) != 12:
        return ''
    return ':'.join(clean[index:index + 2] for index in range(0, 12, 2)).lower()


def env_var_from_hostname(hostname: str) -> str:
    value = re.sub(r'[^A-Z0-9_]', '_', f'{hostname}_SSH_PASSWORD'.upper())
    if re.match(r'^[0-9]', value):
        value = f'_{value}'
    return value


def safe_hostname(value: str, prefix: str) -> str:
    candidate = value.strip().lower()
    if candidate and not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', candidate):
        candidate = candidate.split('.', 1)[0]
    if not candidate or re.fullmatch(r'\d+\.\d+\.\d+\.\d+', candidate):
        candidate = f'{prefix}-{value.replace(".", "-")}'
    candidate = re.sub(r'[^a-z0-9_.-]+', '-', candidate).strip('-')
    if not candidate:
        candidate = prefix
    if re.match(r'^[0-9]', candidate):
        candidate = f'{prefix}-{candidate}'
    return candidate


def unique_hostname(base_name: str, root_hosts: dict[str, dict[str, str]], groups: dict[str, dict[str, dict[str, str]]]) -> str:
    existing = set(root_hosts)
    for group_hosts in groups.values():
        existing.update(group_hosts)
    if base_name not in existing:
        return base_name
    suffix = 2
    while f'{base_name}-{suffix}' in existing:
        suffix += 1
    return f'{base_name}-{suffix}'


def reverse_dns(address: str) -> str:
    try:
        name = socket.gethostbyaddr(address)[0]
    except (OSError, socket.herror):
        return ''
    return name.rstrip('.')


def parse_arp_scan(output: str) -> list[dict[str, str]]:
    hosts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    row_pattern = re.compile(
        r'^(?P<address>\d{1,3}(?:\.\d{1,3}){3})\s+'
        r'(?P<mac>[0-9A-Fa-f:]{17})\s*'
        r'(?P<vendor>.*)$'
    )
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = row_pattern.match(line)
        if not match:
            continue
        address = match.group('address')
        mac = normalise_mac(match.group('mac'))
        vendor = match.group('vendor').strip()
        key = (address, mac)
        if key in seen:
            continue
        seen.add(key)
        hosts.append({'address': address, 'mac': mac, 'vendor': vendor, 'name': reverse_dns(address)})
    return hosts


def index_inventory(root_hosts: dict[str, dict[str, str]], groups: dict[str, dict[str, dict[str, str]]]) -> tuple[dict[str, tuple[str, str, dict[str, str]]], dict[str, tuple[str, str, dict[str, str]]]]:
    by_address: dict[str, tuple[str, str, dict[str, str]]] = {}
    by_mac: dict[str, tuple[str, str, dict[str, str]]] = {}

    for host_name, values in root_hosts.items():
        address = values.get('ansible_host', host_name)
        by_address[address] = ('', host_name, values)
        mac = normalise_mac(values.get('homelab_mac_address', ''))
        if mac:
            by_mac[mac] = ('', host_name, values)

    for group_name, group_hosts in groups.items():
        for host_name, values in group_hosts.items():
            address = values.get('ansible_host', host_name)
            by_address[address] = (group_name, host_name, values)
            mac = normalise_mac(values.get('homelab_mac_address', ''))
            if mac:
                by_mac[mac] = (group_name, host_name, values)

    return by_address, by_mac


def password_var(strategy: str, hostname: str) -> str:
    if strategy == 'none':
        return ''
    return env_var_from_hostname(hostname)


def build_new_host(args: argparse.Namespace, host: dict[str, str], hostname: str, now: str) -> dict[str, str]:
    values = {
        'ansible_host': host['address'],
        'ansible_user': args.ssh_user,
        'ansible_port': args.ssh_port,
        'ansible_ssh_private_key_file': args.ssh_key_file,
        'ansible_python_interpreter': args.python_interpreter,
        'homelab_mac_address': host['mac'],
        'homelab_discovery_source': 'arp-scan',
        'homelab_last_seen': now,
    }
    if host.get('vendor'):
        values['homelab_mac_vendor'] = host['vendor']
    if host.get('name'):
        values['homelab_discovered_name'] = host['name']
    password_variable = password_var(args.password_var_strategy, hostname)
    if password_variable:
        values['ansible_password'] = "{{ lookup('env', '" + password_variable + "') }}"
        values['homelab_ssh_password_var'] = password_variable
    return values


def update_existing_host(values: dict[str, str], host: dict[str, str], now: str) -> bool:
    changed = False
    updates = {
        'homelab_mac_address': host['mac'],
        'homelab_discovery_source': 'arp-scan',
        'homelab_last_seen': now,
    }
    if host.get('vendor'):
        updates['homelab_mac_vendor'] = host['vendor']
    if host.get('name'):
        updates['homelab_discovered_name'] = host['name']

    for key, value in updates.items():
        if value and values.get(key) != value:
            values[key] = value
            changed = True
    return changed


def write_report(report_file: Path, report_rows: list[tuple[str, str, str]]) -> None:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'Inventory network sync report',
        '=============================',
        '',
        f'Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}',
        '',
        f'{"Status":<10} {"Host":<28} Detail',
        f'{"------":<10} {"----":<28} ------',
    ]
    for status, hostname, detail in report_rows:
        lines.append(f'{status:<10} {hostname:<28} {detail}')
    report_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.chmod(report_file, 0o600)


def sync_inventory(args: argparse.Namespace, arp_scan_output: str) -> int:
    inventory_file = Path(args.inventory_file)
    report_file = Path(args.report_file)
    root_hosts, groups = INVENTORY_MANAGER.read_inventory(inventory_file)
    groups.setdefault(args.group, {})
    by_address, by_mac = index_inventory(root_hosts, groups)
    discovered_hosts = parse_arp_scan(arp_scan_output)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    changed = 0
    added = 0
    updated = 0
    skipped = 0
    report_rows: list[tuple[str, str, str]] = []

    for host in discovered_hosts:
        match = by_address.get(host['address']) or by_mac.get(host['mac'])
        if match:
            group_name, host_name, values = match
            if not args.update_existing:
                skipped += 1
                report_rows.append(('SKIPPED', host_name, f'existing host at {host["address"]}'))
                continue
            if update_existing_host(values, host, now):
                changed += 1
                updated += 1
                report_rows.append(('UPDATED', host_name, f'ansible_host={host["address"]}, mac={host["mac"]}, group={group_name or "root"}'))
            else:
                report_rows.append(('OK', host_name, f'no inventory changes for {host["address"]}'))
            continue

        if not args.add_new:
            skipped += 1
            report_rows.append(('SKIPPED', host['address'], 'new host creation disabled'))
            continue

        name_source = host.get('name') or host['address']
        hostname = unique_hostname(safe_hostname(name_source, args.hostname_prefix), root_hosts, groups)
        groups[args.group][hostname] = build_new_host(args, host, hostname, now)
        by_address[host['address']] = (args.group, hostname, groups[args.group][hostname])
        by_mac[host['mac']] = (args.group, hostname, groups[args.group][hostname])
        changed += 1
        added += 1
        report_rows.append(('ADDED', hostname, f'ansible_host={host["address"]}, mac={host["mac"]}, group={args.group}'))

    if changed and not args.dry_run:
        INVENTORY_MANAGER.write_inventory(inventory_file, root_hosts, groups)

    write_report(report_file, report_rows)

    print('\nInventory network sync')
    print('----------------------')
    print(f'Discovered hosts: {len(discovered_hosts)}')
    print(f'Added: {added}')
    print(f'Updated: {updated}')
    print(f'Skipped: {skipped}')
    print(f'changed: {changed}')
    print(f'Dry run: {"yes" if args.dry_run else "no"}')
    print(f'Inventory file: {inventory_file}')
    print(f'Report file: {report_file}')
    for status, hostname, detail in report_rows:
        print(f'{status:7} {hostname:30} {detail}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Update homelab Ansible inventory from arp-scan output.')
    parser.add_argument('--inventory-file', required=True)
    parser.add_argument('--report-file', required=True)
    parser.add_argument('--group', required=True)
    parser.add_argument('--hostname-prefix', default='host')
    parser.add_argument('--ssh-user', required=True)
    parser.add_argument('--ssh-port', default='22')
    parser.add_argument('--ssh-key-file', default='~/.ssh/homelab_ed25519')
    parser.add_argument('--python-interpreter', default='auto_silent')
    parser.add_argument('--password-var-strategy', choices=('hostname', 'none'), default='hostname')
    parser.add_argument('--update-existing', dest='update_existing', action='store_true')
    parser.add_argument('--no-update-existing', dest='update_existing', action='store_false')
    parser.set_defaults(update_existing=True)
    parser.add_argument('--add-new', dest='add_new', action='store_true')
    parser.add_argument('--no-add-new', dest='add_new', action='store_false')
    parser.set_defaults(add_new=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', dest='dry_run', action='store_false')
    args = parser.parse_args()

    return sync_inventory(args, sys.stdin.read())


if __name__ == '__main__':
    sys.exit(main())
