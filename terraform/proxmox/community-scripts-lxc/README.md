# Proxmox Community Scripts LXC Terraform

Deploys Proxmox LXC containers using the Proxmox Community Scripts via SSH remote execution.

## Ownership model

This Terraform stack owns only the deployment wrapper and Terraform state. The LXC creation logic remains owned by the upstream Community Scripts project. Local runtime files and secrets remain under the repository `state/` model.

## Secrets model

Do not commit passwords in Terraform files.

Create a local-only file from the example:

```bash
cp terraform/proxmox/community-scripts-lxc/examples/secrets.auto.tfvars.example terraform/proxmox/community-scripts-lxc/secrets.auto.tfvars
```

Then update the password value locally. The file is ignored by `.gitignore`.

## Container configuration

Copy the example container file before first use:

```bash
cp terraform/proxmox/community-scripts-lxc/containers.auto.tfvars.json.example terraform/proxmox/community-scripts-lxc/containers.auto.tfvars.json
```

The copied `.auto.tfvars.json` file is local-only and ignored by `.gitignore`.

## Recommended Taskfile usage

From the repository root:

```bash
task terraform:lxc:init
task terraform:lxc:plan
task terraform:lxc:apply
```

Destroy Terraform-created LXCs:

```bash
task terraform:lxc:destroy
```

Destroy a single Terraform-created LXC:

```bash
task terraform:lxc:destroy:target TERRAFORM_LXC_TARGET=dns01
```

Existing LXCs that were skipped during apply are not destroyed because no Terraform creation marker exists on the Proxmox host.

## Direct Terraform usage

```bash
cd terraform/proxmox/community-scripts-lxc
terraform init
terraform plan \
  -var="proxmox_host=192.168.20.10" \
  -var="proxmox_ssh_user=root" \
  -var="proxmox_ssh_private_key_file=~/.ssh/homelab_ed25519"
terraform apply -parallelism=2
```

## Environment loading

The repository Taskfile explicitly sources `state/config/.env` because some Task versions do not support the `--dotenv` CLI flag. You can therefore run the Terraform tasks directly from the repository root without manually exporting `.env` values.

For apply, the task also attempts to decrypt `state/secrets/passwords/passwords.enc.env` with SOPS and age. It expects either:

```bash
HOMELAB_LXC_ROOT_PASSWORD=<container-root-password>
```

or the variable referenced by `PROXMOX_SSH_PASSWORD_VAR`. The task writes the password into a local-only generated file:

```text
terraform/proxmox/community-scripts-lxc/secrets.auto.tfvars.json
```

This file is ignored by Git and should not be committed.
