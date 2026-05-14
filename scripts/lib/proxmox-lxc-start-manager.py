#!/usr/bin/env python3
"""
File: scripts/lib/proxmox-lxc-start-manager.py
Purpose:
  Start Terraform-defined Proxmox LXC containers that exist but are not running.
Notes:
  - This script reads container IDs from containers.auto.tfvars.json.
  - It connects to the Proxmox host over SSH and uses pct status/start.
  - It does not handle, print, or require LXC root passwords.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import socket
import ipaddress


@dataclass(frozen=True)
class Container:
    name: str
    ctid: int
    ssh_host: str
    ssh_port: int


def load_containers(path: Path) -> list[Container]:
    if not path.exists():
        raise SystemExit(f"ERROR: Container tfvars file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: Could not parse JSON from {path}: {exc}") from exc

    raw_containers: Any = data.get("containers", {})
    if not isinstance(raw_containers, dict):
        raise SystemExit(f"ERROR: Expected {path} to contain a top-level containers object.")

    containers: list[Container] = []
    for name, values in sorted(raw_containers.items()):
        if not isinstance(values, dict):
            continue
        ctid = values.get("ctid")
        if ctid is None:
            raise SystemExit(f"ERROR: Container {name} is missing ctid in {path}.")

        ssh_host = str(values.get("ansible_host") or values.get("ip") or "").strip()
        ip_cidr = str(values.get("ip_cidr") or "").strip()
        if not ssh_host and ip_cidr:
            try:
                ssh_host = str(ipaddress.ip_interface(ip_cidr).ip)
            except ValueError as exc:
                raise SystemExit(f"ERROR: Container {name} has invalid ip_cidr {ip_cidr!r}.") from exc

        try:
            containers.append(Container(name=str(name), ctid=int(ctid), ssh_host=ssh_host, ssh_port=int(values.get("ssh_port", 22))))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"ERROR: Container {name} has invalid ctid or ssh_port.") from exc

    if not containers:
        raise SystemExit(f"ERROR: No containers found in {path}.")

    return containers


def build_ssh_base(args: argparse.Namespace) -> list[str]:
    target = f"{args.proxmox_user}@{args.proxmox_host}"
    base = [
        "ssh",
        "-i",
        args.ssh_key_file,
        "-p",
        str(args.proxmox_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        target,
    ]
    return base


def run_remote(ssh_base: list[str], command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ssh_base + [command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def pct_status(ssh_base: list[str], ctid: int) -> tuple[bool, str]:
    result = run_remote(ssh_base, f"pct status {ctid}")
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    return result.returncode == 0, output


def is_running(status_output: str) -> bool:
    return "status: running" in status_output.lower()


def wait_until_running(ssh_base: list[str], container: Container, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        exists, status_output = pct_status(ssh_base, container.ctid)
        if exists and is_running(status_output):
            return True
        time.sleep(3)
    return False


def tcp_connects(host: str, port: int, timeout_seconds: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def wait_until_ssh_reachable(container: Container, timeout_seconds: int) -> bool:
    if not container.ssh_host:
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        if tcp_connects(container.ssh_host, container.ssh_port):
            return True
        time.sleep(5)
    return False


def start_container(
    ssh_base: list[str],
    container: Container,
    timeout_seconds: int,
    wait_for_ssh: bool,
    ssh_wait_seconds: int,
) -> tuple[str, str]:
    exists, status_output = pct_status(ssh_base, container.ctid)
    if not exists:
        return "MISSING", f"{container.name} ({container.ctid}) was not found on Proxmox."

    if is_running(status_output):
        if wait_for_ssh and not wait_until_ssh_reachable(container, ssh_wait_seconds):
            return "FAILED", f"{container.name} ({container.ctid}) is running, but SSH did not become reachable on {container.ssh_host}:{container.ssh_port} within {ssh_wait_seconds} seconds."
        return "RUNNING", f"{container.name} ({container.ctid}) is already running."

    start_result = run_remote(ssh_base, f"pct start {container.ctid}")
    if start_result.returncode != 0:
        details = "\n".join(part.strip() for part in [start_result.stdout, start_result.stderr] if part.strip())
        return "FAILED", f"{container.name} ({container.ctid}) failed to start. {details}".strip()

    if wait_until_running(ssh_base, container, timeout_seconds):
        if wait_for_ssh and not wait_until_ssh_reachable(container, ssh_wait_seconds):
            return "FAILED", f"{container.name} ({container.ctid}) started, but SSH did not become reachable on {container.ssh_host}:{container.ssh_port} within {ssh_wait_seconds} seconds."
        return "STARTED", f"{container.name} ({container.ctid}) started successfully."

    return "FAILED", f"{container.name} ({container.ctid}) did not reach running state within {timeout_seconds} seconds."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Terraform-defined Proxmox LXC containers.")
    parser.add_argument("--containers-file", required=True)
    parser.add_argument("--proxmox-host", required=True)
    parser.add_argument("--proxmox-user", default="root")
    parser.add_argument("--proxmox-port", default="22")
    parser.add_argument("--ssh-key-file", required=True)
    parser.add_argument("--wait-seconds", type=int, default=90)
    parser.add_argument("--wait-ssh", action="store_true", help="Wait for SSH TCP connectivity after each container is running.")
    parser.add_argument("--ssh-wait-seconds", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    containers = load_containers(Path(args.containers_file))
    ssh_base = build_ssh_base(args)

    print("Proxmox LXC start report")
    print("------------------------")

    failed = 0
    changed = 0
    for container in containers:
        status, message = start_container(ssh_base, container, args.wait_seconds, args.wait_ssh, args.ssh_wait_seconds)
        if status in {"STARTED"}:
            changed += 1
        if status in {"FAILED", "MISSING"}:
            failed += 1
        print(f"{status:<8} {message}")

    print(f"\nContainers checked: {len(containers)}; started: {changed}; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
