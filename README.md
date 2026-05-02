# Homelab

Homelab is a Taskfile-driven control-plane repository for building and operating a personal Proxmox-focused lab environment.

The repository is designed around a simple operating model: `install.sh` bootstraps or updates the repo, then `Taskfile.yml` becomes the main entry point for day-to-day setup and maintenance.

## What this repo contains

```text
.
├── install.sh                                  # Bootstrap installer for Debian/Ubuntu systems
├── Taskfile.yml                                # Root operational entry point
├── ansible/
│   └── requirements.yml                        # Version-controlled Ansible Galaxy collections and roles
├── taskfile/
│   ├── apps.Taskfile.yml                       # Python, pipx, Ansible, Terraform, Packer, and Galaxy content
│   ├── github.Taskfile.yml                     # Git and GitHub CLI setup and audit tasks
│   ├── health.Taskfile.yml                     # Consolidated health checks
│   ├── passwords.Taskfile.yml                  # SOPS, age, password, backup, audit, and cleanup tasks
│   ├── env_create.Taskfile.yml                 # Baseline state and Ansible inventory creation
│   └── ssh.Taskfile.yml                        # SSH key, copy-id, and audit tasks
├── scripts/
│   ├── banner/banner.sh                        # Homelab terminal banner
│   └── lib/
│       ├── add_shared_drives.sh                # Interactive CIFS shared-drive helper
│       ├── audit-ansible-requirements.py       # Requirements parser for Ansible audit output
│       ├── ensure-executable-scripts.sh        # Script permission normalisation
│       ├── health-check.sh                     # Shared health and audit output helpers
│       ├── inventory-manager.py                # Ansible inventory add/update helper
│       └── terminal-colours.sh                 # Shared terminal colour helpers
├── state/                                      # Local runtime state; ignored by Git
└── .sops.yaml                                  # Local SOPS rules; generated and ignored by Git
```

## Operating model

This repo separates bootstrap, orchestration, secrets, and service helpers.

- `install.sh` prepares the local checkout, records local environment values, ensures scripts are executable, and installs Task if required.
- `Taskfile.yml` is the control plane after installation.
- `taskfile/passwords.Taskfile.yml` manages SOPS and age-based encrypted password files.
- `taskfile/github.Taskfile.yml` manages Git, GitHub CLI identity, authentication, and audit status.
- `taskfile/health.Taskfile.yml` provides a consolidated operational health check.
- `taskfile/ssh.Taskfile.yml` manages SSH client tooling, the homelab Ed25519 key, copy-id, and per-server audit status.
- `state/` stores local runtime configuration, secrets, backups, audit reports, and generated files. It is intentionally excluded from Git.

## Supported environment

The bootstrap flow is currently intended for Debian/Ubuntu-family systems.

The default target environments are:

- `prod` → `~/app/homelab_20260501`
- `dev` → `~/Github/homelab_20260501`

The installer supports environment overrides such as `SETUP`, `TARGET_DIR`, `HOMELAB_BRANCH`, `HOMELAB_GIT_PROTOCOL`, and `NONINTERACTIVE`.

## Quick start

Run the installer:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Fouchger/homelab_20260501/main/install.sh)"
```

Then enter the repo and view the safe task list:

```bash
cd ~/app/homelab_20260501
# or, for dev installs:
cd ~/Github/homelab_20260501

task help
```

Run the standard setup flow:

```bash
task homelab:setup
```

## Common tasks

```bash
task help
```

Shows the safe operator tasks.

```bash
task passwords:setup
```

Installs password tooling, configures SOPS and age, generates key material, creates an offline backup bundle, creates or encrypts the password file, and removes runtime plaintext files.

```bash
task passwords:edit
```

Edits the encrypted password file through SOPS using the configured editor.

```bash
task passwords:audit
```

Creates a password hygiene report without printing secret values.

```bash
task passwords:cleanup
```

Removes runtime plaintext password files and temporary decrypted files.

```bash
task ssh:setup
```

Installs SSH client tooling, calls `env_create:inventory:init` to create `state/ansible/inventory.yml` if missing, creates the homelab Ed25519 key if missing, copies the public key to remote inventory hosts using `ansible_host`, normalises successful hosts to key-based Ansible authentication, and reports per-server status.

```bash
task ssh:normalise-auth
```

After `ssh-copy-id` succeeds, updates inventory hosts to use the homelab private key for steady-state Ansible access and removes runtime `ansible_password` from those hosts. The secret variable reference is retained as metadata for bootstrap and recovery.

```bash
task ssh:audit
```

Reports SSH key status, auth mode, and passwordless SSH status for each server in the inventory. The logical inventory hostname stays separate from the SSH connection target stored in `ansible_host`.

```bash
task apps:setup
```

Installs Python, pipx, Ansible, Terraform, Packer, common prerequisites, and Ansible Galaxy content from `ansible/requirements.yml`.

```bash
task apps:audit
```

Reports installed tooling versions and Ansible Galaxy content status using a consistent health output format.

```bash
task health:check
```

Runs a consolidated health check across repository files and core commands.

```bash
task health:all
```

Runs the consolidated health check plus detailed GitHub, application, SSH, and password audits.

## Secrets model

Secrets are managed with SOPS and age.

The main encrypted password file is:

```text
state/secrets/passwords/passwords.enc.env
```

Runtime plaintext files are temporary and should be removed with:

```bash
task passwords:cleanup
```

Generated key material and backup bundles live under `state/secrets/` and `state/backups/`. These are local-only and must not be committed.

After running `task passwords:backup:offline`, move the backup bundle to offline storage.


## Inventory model

`state/ansible/inventory.yml` separates the logical Ansible hostname from the SSH connection target:

```yaml
all:
  hosts:
    local:
      ansible_host: 127.0.0.1
      ansible_connection: local
      ansible_user: root
      ansible_port: 22
  children:
    proxmox:
      hosts:
        pve01:
          ansible_host: 192.168.20.10
          ansible_user: root
          ansible_port: 22
          ansible_ssh_private_key_file: /root/.ssh/homelab_ed25519
          ansible_python_interpreter: auto_silent
          homelab_mac_address: 9c:6b:00:06:49:a7
          homelab_ssh_password_var: PVE01_SSH_PASSWORD
```

Use `task env_create:inventory:add` for the guided flow. It asks for the logical hostname and the SSH IP address or DNS name separately, then derives follow-on hostnames, IP addresses, MAC addresses, and password variable names for additional servers.

## Local state and generated files

The following are expected to be local runtime artefacts and are ignored by Git:

- `state/config/.env`
- `state/ansible/inventory.yml`
- `state/secrets/`
- `state/backups/`
- `.sops.yaml`
- plaintext runtime password files

## File ownership rules

- `install.sh` is the only creator of `state/config/.env`. Other tasks may update it only when it already exists.
- `taskfile/passwords.Taskfile.yml` is the only creator of `state/secrets/passwords/passwords.enc.env`. Other tasks may update it only when it already exists and is a valid SOPS file.
- `taskfile/env_create.Taskfile.yml` may create `state/ansible/inventory.yml` when it is missing.

## Development notes

The repo is still in active development. The current installer intentionally uses the live branch for convenience.

Recommended conventions:

- Put shared paths and repo-wide variables in `Taskfile.yml`.
- Keep task-specific URLs, versions, and policy choices in the relevant included Taskfile.
- Keep reusable install manifests, such as Ansible Galaxy content, in committed files instead of embedded shell blocks.
- Use `scripts/lib/health-check.sh` for consistent audit and health-check output.
- Use strict shell handling in executable scripts and inline Taskfile shell blocks.
- Keep destructive or plaintext-exposing tasks out of `task help`.

## Licence

This repository is licensed under GPL-3.0. See `LICENSE`.

## Operational health and capabilities

The repo now separates installed tools from operational capability. Run:

```bash
task health:check
task health:capabilities
task health:setup-state
task health:all
```

The health framework checks binaries, apt packages, pipx-installed tools, required files, SOPS readiness, and first-run/repeat-run state markers. SOPS readiness is reported explicitly as `SOPS READY` or `SOPS LOCKED` without printing secret values.

## Ansible connectivity

After inventory and SSH setup, validate actual Ansible connectivity with:

```bash
task ansible:ping
```

This uses `state/ansible/inventory.yml`, reports per-host success or failure, and does not fail the wider setup flow when one host is unreachable. Password variables may still be loaded for bootstrap or recovery, but SSH key-based access is the preferred steady-state path.

## Network discovery

Use nmap-based discovery to find devices that are not yet represented in the inventory:

```bash
task env_create:inventory:discover DISCOVERY_CIDR=192.168.20.0/24
```

The task writes an advisory report to `state/ansible/discovery-report.txt`. It does not modify the inventory automatically; add selected hosts with `task env_create:inventory:add`.

## Terraform LXC deployment

This repository includes a Terraform stack for deploying Proxmox LXCs through the Proxmox Community Scripts while keeping secrets local-only.

```bash
cp terraform/proxmox/community-scripts-lxc/containers.auto.tfvars.json.example terraform/proxmox/community-scripts-lxc/containers.auto.tfvars.json
```

The Taskfile generates `terraform/proxmox/community-scripts-lxc/secrets.auto.tfvars.json` from SOPS or environment variables. Do not create or commit this file manually.

Run through Taskfile from the repository root:

```bash
task terraform:lxc:init
task terraform:lxc:plan
task terraform:lxc:apply
```

Destroy Terraform-created LXCs only:

```bash
task terraform:lxc:destroy
```

Destroy one Terraform-created LXC:

```bash
task terraform:lxc:destroy:target TERRAFORM_LXC_TARGET=plex01
```

Existing containers skipped during `apply` are preserved during `destroy` because the Terraform workflow only destroys LXCs with a creation marker on the Proxmox host.
