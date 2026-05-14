# Inventory Network Discovery

This repository includes an Ansible playbook and role that scan the local network with `arp-scan` and synchronise discovered devices into `state/ansible/inventory.yml`.

## Run

```bash
task ansible:inventory:scan
```

To scan a specific network instead of the local interface network:

```bash
task ansible:inventory:scan DISCOVERY_TARGET=192.168.20.0/24
```

To bind the scan to a specific interface:

```bash
task ansible:inventory:scan DISCOVERY_INTERFACE=eth0
```

To preview changes without writing the inventory:

```bash
task ansible:inventory:scan DISCOVERY_DRY_RUN=true
```

## Inventory behaviour

Existing hosts are matched by `ansible_host` first, then by `homelab_mac_address`. Existing connection details are preserved.

For new hosts, the role writes the same core fields used by the current inventory tooling:

- `ansible_host`
- `ansible_user`
- `ansible_port`
- `ansible_ssh_private_key_file`
- `ansible_python_interpreter`
- `ansible_password`
- `homelab_ssh_password_var`
- `homelab_mac_address`

The scan also records discovery metadata:

- `homelab_discovery_source`
- `homelab_last_seen`
- `homelab_mac_vendor`
- `homelab_discovered_name`, when reverse DNS is available

`homelab_vm_lxc_id` is preserved for existing hosts but is not inferred for new hosts because `arp-scan` cannot reliably determine Proxmox VM or LXC IDs.
