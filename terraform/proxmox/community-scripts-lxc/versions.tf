# ==============================================================================
# File: terraform/proxmox/community-scripts-lxc/versions.tf
# Purpose:
#   Pin Terraform and provider versions for Proxmox Community Scripts LXC deployment.
# ==============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}
