# ==============================================================================
# File: terraform/proxmox/community-scripts-lxc/locals.tf
# Purpose:
#   Define shared local values for deployment commands.
# ============================================================================== 

locals {
  term          = "xterm"
  install_mode  = "default"
  ipv6_method   = "none"
  ssh_enabled   = "yes"
  marker_dir    = "/var/lib/homelab-terraform-lxc"
}
