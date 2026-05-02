# ==============================================================================
# File: terraform/proxmox/community-scripts-lxc/outputs.tf
# Purpose:
#   Show non-secret container deployment metadata.
# ============================================================================== 

output "container_summary" {
  description = "Configured containers."
  value = {
    for name, container in var.containers : name => {
      ctid        = container.ctid
      app         = container.app
      ip_cidr     = container.ip_cidr
      vlan        = container.vlan
      mac_address = container.mac_address
    }
  }
}
