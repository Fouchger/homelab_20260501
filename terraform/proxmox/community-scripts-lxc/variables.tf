# ==============================================================================
# File: terraform/proxmox/community-scripts-lxc/variables.tf
# Purpose:
#   Define input variables for Proxmox Community Scripts LXC deployment.
# Notes:
#   - Container passwords are provided through container_passwords, not committed
#     in container definitions.
# ==============================================================================

variable "proxmox_host" {
  description = "Proxmox SSH host or IP address. Usually PROXMOX_SSH_HOST from state/config/.env."
  type        = string
}

variable "proxmox_ssh_user" {
  description = "SSH user used to run Community Scripts on the Proxmox host."
  type        = string
  default     = "root"
}

variable "proxmox_ssh_port" {
  description = "SSH port for the Proxmox host."
  type        = number
  default     = 22
}

variable "proxmox_ssh_private_key_file" {
  description = "Path to the SSH private key used to connect to the Proxmox host."
  type        = string
  default     = "~/.ssh/homelab_ed25519"
}

variable "controlplane_ssh_public_key" {
  description = "SSH public key from the control plane to install into created LXCs for root SSH access."
  type        = string
  default     = ""
  sensitive   = true
}

variable "script_base" {
  description = "Pinned base URL for Proxmox Community Scripts container scripts. Review and update this deliberately when adopting upstream changes."
  type        = string
  default     = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/2026-05-12/ct"
}


variable "script_sha256" {
  description = "Optional map of Community Script app names to expected SHA-256 checksums. Empty values skip checksum validation."
  type        = map(string)
  default     = {}
}

variable "destroy_lxc_on_terraform_destroy" {
  description = "Destroy Terraform-created LXCs when terraform destroy is run. Existing containers skipped during apply are not destroyed."
  type        = bool
  default     = true
}

variable "container_passwords" {
  description = "Sensitive map of password keys to root passwords used by the containers. Supply through secrets.auto.tfvars or TF_VAR_container_passwords."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "containers" {
  description = "Community Scripts LXC containers to deploy."
  type = map(object({
    ctid        = number
    app         = string
    cpu         = number
    ram         = number
    disk        = number
    bridge      = string
    ip_cidr     = string
    gateway     = string
    vlan        = number
    mac_address  = string
    password_key = string
    tags         = string

    gpu          = string
    unprivileged = number
    nesting      = number
    diagnostics  = string
    tun          = string
    keyctl       = number
    mount_fs     = string
    timezone     = string

    nameserver = optional(string)
    protection = optional(string, "yes")
    verbose    = optional(string, "no")
  }))
}
