# Plex Ansible Configuration

## Purpose

This document explains how the homelab Plex Ansible flow is structured, how it interfaces with Plex, and which settings are applied by default.

## Folder Structure

The Plex configuration uses the standard Ansible layout:

- `ansible/playbooks/plex-configure.yml` is the operator entry point.
- `ansible/group_vars/plex.yml` maps environment and SOPS-loaded values into Ansible variables.
- `ansible/roles/homelab_shared_drives` configures SMB/CIFS shares using the existing helper script.
- `ansible/roles/plex_server` claims Plex and ensures the Plex service is running.

## Operator Flow

Run:

```bash
task ansible:plex:configure
```

The task first runs `ansible:plex:prepare-vars`.

Missing non-secret values are prompted once and saved into:

```text
state/config/.env
```

Missing secret values are prompted once and saved into the SOPS encrypted password file:

```text
state/secrets/passwords/passwords.enc.env
```

The task then loads both files into the process environment and runs:

```bash
ansible-playbook -i state/ansible/inventory.yml ansible/playbooks/plex-configure.yml
```

## Plex Interface

The playbook interfaces with Plex through the local Plex Media Server HTTP API from inside each Plex server.

Default endpoint:

```text
http://127.0.0.1:32400/myplex/claim?token=<PLEX_CLAIM_TOKEN>
```

The role sends a `POST` request to this endpoint using Ansible `uri`.

Important notes:

- `PLEX_CLAIM_TOKEN` comes from `https://www.plex.tv/claim`.
- Plex claim tokens are short-lived, so the saved value may need to be refreshed before a future rerun.
- The role does not create Plex libraries yet. It prepares storage, claims the server, and ensures the service is enabled and running.

## Shared Drive Interface

The shared-drive role keeps the existing project intent by using:

```text
scripts/lib/add_shared_drives.sh
```

The role copies that script to each Plex server and feeds it the OMV host, skip/replace behaviour, and share names non-interactively. It writes `/etc/samba/omv-cred` before running the helper so the script does not need to prompt for the SMB password.

## Default Settings

| Setting | Default | Stored in |
| --- | --- | --- |
| Plex Ansible target | `plex` | `state/config/.env` |
| OMV SMB host | `192.168.30.20` | `state/config/.env` |
| OMV SMB username | `omvuser` | `state/config/.env` |
| OMV SMB password | prompted | SOPS password file |
| Shared drives | `TB4a,TB5a,TB10a,TB10b,TB16a` | `state/config/.env` |
| Existing fstab behaviour | `s` skip | `state/config/.env` |
| Plex API host | `127.0.0.1` | `state/config/.env` |
| Plex API port | `32400` | `state/config/.env` |
| Plex service name | `plexmediaserver` | `state/config/.env` |
| Plex claim token | prompted | SOPS password file |

## Ownership and Permissions

- `/etc/samba/omv-cred` is owned by `root:root` with mode `0600`.
- Mount directories under `/mnt` are owned by `root:root` with mode `0755`.
- The copied shared-drive helper is owned by `root:root` with mode `0755`.
- `state/config/.env` is mode `0600`.
- `state/secrets/passwords/passwords.enc.env` is mode `0600` and encrypted by SOPS.

## Current Scope

The current role configures the server foundation only:

- SMB/CIFS shared media mounts.
- Plex service enabled and started.
- Plex server claim against the signed-in Plex account.

The next logical enhancement is an authenticated Plex library role using a permanent Plex token after the claim has completed. That would allow automatic creation of Movies, TV, Music, and Photos libraries against the mounted folders.
