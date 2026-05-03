# ==============================================================================
# File: terraform/proxmox/community-scripts-lxc/main.tf
# Purpose:
#   Deploy Proxmox LXC containers using Community Scripts over SSH.
# Notes:
#   - Existing CTIDs are skipped and do not create a destroy marker.
#   - terraform destroy only destroys containers that this module created and
#     marked on the Proxmox host.
# ==============================================================================

resource "null_resource" "community_script_lxc" {
  for_each = var.containers

  triggers = {
    ctid                              = tostring(each.value.ctid)
    hostname                          = each.key
    app                               = each.value.app
    cpu                               = tostring(each.value.cpu)
    ram                               = tostring(each.value.ram)
    disk                              = tostring(each.value.disk)
    bridge                            = each.value.bridge
    ip_cidr                           = each.value.ip_cidr
    gateway                           = each.value.gateway
    vlan                              = tostring(each.value.vlan)
    mac_address                       = each.value.mac_address
    proxmox_host                      = var.proxmox_host
    proxmox_ssh_user                  = var.proxmox_ssh_user
    proxmox_ssh_port                  = tostring(var.proxmox_ssh_port)
    proxmox_ssh_private_key_file      = var.proxmox_ssh_private_key_file
    destroy_lxc_on_terraform_destroy  = tostring(var.destroy_lxc_on_terraform_destroy)
    marker_dir                        = local.marker_dir
  }

  connection {
    type        = "ssh"
    host        = self.triggers.proxmox_host
    user        = self.triggers.proxmox_ssh_user
    port        = tonumber(self.triggers.proxmox_ssh_port)
    private_key = file(pathexpand(self.triggers.proxmox_ssh_private_key_file))
    timeout     = "10m"
  }

  provisioner "remote-exec" {
    inline = [
      <<-EOT
      set -euo pipefail

      export TERM=${local.term}

      marker_dir=${jsonencode(local.marker_dir)}
      marker_file="${local.marker_dir}/${each.value.ctid}.created_by_terraform"

      mkdir -p "$marker_dir"

      if pct status ${each.value.ctid} >/dev/null 2>&1; then
        echo "[INFO] Container ID ${each.value.ctid} already exists. Skipping ${each.key}."
        exit 0
      fi

      container_password=${jsonencode(try(var.container_passwords[each.value.password_key], ""))}

      if [ -z "$container_password" ]; then
        echo "[ERROR] Missing container password for key ${each.value.password_key}." >&2
        echo "        Add it to secrets.auto.tfvars or set TF_VAR_container_passwords." >&2
        exit 1
      fi

      echo "[INFO] Deploying ${each.key} using Community Script ${each.value.app}."

      env \
        TERM=${jsonencode(local.term)} \
        mode=${jsonencode(local.install_mode)} \
        MODE=${jsonencode(local.install_mode)} \
        CTID=${each.value.ctid} \
        var_ctid=${each.value.ctid} \
        var_unprivileged=${each.value.unprivileged} \
        var_cpu=${each.value.cpu} \
        var_ram=${each.value.ram} \
        var_disk=${each.value.disk} \
        var_hostname=${jsonencode(each.key)} \
        var_brg=${jsonencode(each.value.bridge)} \
        var_net=${jsonencode(each.value.ip_cidr)} \
        var_gateway=${jsonencode(each.value.gateway)} \
        var_vlan=${each.value.vlan} \
        var_mac=${jsonencode(each.value.mac_address)} \
        var_ns=${jsonencode(coalesce(each.value.nameserver, each.value.gateway))} \
        var_ssh=${jsonencode(local.ssh_enabled)} \
        var_ssh_authorized_key=${jsonencode(var.controlplane_ssh_public_key)} \
        var_pw="$container_password" \
        var_ipv6_method=${jsonencode(local.ipv6_method)} \
        var_nesting=${each.value.nesting} \
        var_gpu=${jsonencode(each.value.gpu)} \
        var_protection=${jsonencode(each.value.protection)} \
        var_tags=${jsonencode("${each.value.tags};automated;terraform")} \
        var_verbose=${jsonencode(each.value.verbose)} \
        var_diagnostics=${jsonencode(each.value.diagnostics)} \
        var_tun=${jsonencode(each.value.tun)} \
        var_keyctl=${each.value.keyctl} \
        var_mount_fs=${jsonencode(each.value.mount_fs)} \
        var_timezone=${jsonencode(each.value.timezone)} \
        bash -c "$(curl -fsSL ${var.script_base}/${each.value.app}.sh)" _ default

      printf '%s\n' "hostname=${each.key}" "ctid=${each.value.ctid}" "app=${each.value.app}" > "$marker_file"
      chmod 600 "$marker_file"

      echo "[SUCCESS] Deployment complete for ${each.key}."
      EOT
    ]
  }

  provisioner "remote-exec" {
    when       = destroy
    on_failure = continue

    inline = [
      <<-EOT
      set -euo pipefail

      marker_file="${self.triggers.marker_dir}/${self.triggers.ctid}.created_by_terraform"

      if [ "${self.triggers.destroy_lxc_on_terraform_destroy}" != "true" ]; then
        echo "[INFO] Terraform LXC destroy is disabled. Leaving ${self.triggers.hostname} (${self.triggers.ctid}) in place."
        exit 0
      fi

      if [ ! -f "$marker_file" ]; then
        echo "[INFO] No Terraform creation marker for ${self.triggers.hostname} (${self.triggers.ctid}). Leaving container in place."
        exit 0
      fi

      if pct status ${self.triggers.ctid} >/dev/null 2>&1; then
        echo "[INFO] Destroying Terraform-created LXC ${self.triggers.hostname} (${self.triggers.ctid})."
        pct stop ${self.triggers.ctid} >/dev/null 2>&1 || true
        pct destroy ${self.triggers.ctid} --purge
      else
        echo "[INFO] Container ${self.triggers.ctid} no longer exists. Removing marker only."
      fi

      rm -f "$marker_file"
      EOT
    ]
  }
}
