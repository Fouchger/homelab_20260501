#!/usr/bin/env bash
# production-deploy.sh - Production Proxmox Community Scripts deployment runner

set -euo pipefail

export TERM="${TERM:-xterm}"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_BASE="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct"
readonly LOG_DIR="/var/log/proxmox-deployments"
readonly CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/deployment-config.json}"
readonly PARALLEL_JOBS="${PARALLEL_JOBS:-3}"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Logging
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

setup_logging() {
  mkdir -p "$LOG_DIR"
  exec 1> >(tee -a "$LOG_DIR/deployment-$(date +%Y%m%d-%H%M%S).log")
  exec 2>&1
}

log_info() { echo "[INFO] $(date +'%H:%M:%S') - $*"; }
log_error() { echo "[ERROR] $(date +'%H:%M:%S') - $*" >&2; }
log_success() { echo "[SUCCESS] $(date +'%H:%M:%S') - $*"; }

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Validation
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

validate_prerequisites() {
  log_info "Validating prerequisites"

  [ "$EUID" -eq 0 ] || {
    log_error "Must run as root on the Proxmox host"
    exit 1
  }

  command -v jq >/dev/null 2>&1 || {
    log_error "jq is not installed. Run: apt update && apt install -y jq"
    exit 1
  }

  command -v curl >/dev/null 2>&1 || {
    log_error "curl is not installed. Run: apt update && apt install -y curl"
    exit 1
  }

  command -v pct >/dev/null 2>&1 || {
    log_error "pct not found. This must run on a Proxmox host"
    exit 1
  }

  [ -f "$CONFIG_FILE" ] || {
    log_error "Config file not found: $CONFIG_FILE"
    exit 1
  }

  log_success "Prerequisites validated"
}

validate_config() {
  log_info "Validating deployment config"

  jq -e '.containers and (.containers | type == "array") and (.containers | length > 0)' "$CONFIG_FILE" >/dev/null || {
    log_error "Config must contain a non-empty containers array"
    exit 1
  }

  local container_count
  container_count=$(jq '.containers | length' "$CONFIG_FILE")

  for index in $(seq 0 $((container_count - 1))); do
    local hostname app ctid ip_cidr mac_address
    hostname=$(jq -r ".containers[$index].hostname // empty" "$CONFIG_FILE")
    app=$(jq -r ".containers[$index].app // empty" "$CONFIG_FILE")
    ctid=$(jq -r ".containers[$index].ctid // empty" "$CONFIG_FILE")
    ip_cidr=$(jq -r ".containers[$index].ip_cidr // empty" "$CONFIG_FILE")
    mac_address=$(jq -r ".containers[$index].mac_address // empty" "$CONFIG_FILE")

    [ -n "$hostname" ] || { log_error "Container index $index is missing hostname"; exit 1; }
    [ -n "$app" ] || { log_error "Container index $index is missing app"; exit 1; }
    [ -n "$ctid" ] || { log_error "Container $hostname is missing ctid"; exit 1; }
    [ -n "$ip_cidr" ] || { log_error "Container $hostname is missing ip_cidr"; exit 1; }
    [ -n "$mac_address" ] || { log_error "Container $hostname is missing mac_address"; exit 1; }
  done

  log_success "Deployment config validated"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deployment
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

deploy_container() {
  local index="$1"

  local ctid app hostname cpu ram disk bridge ip_cidr gateway vlan mac_address
  local password ssh_key tags gpu unprivileged nesting protection nameserver verbose
  local diagnostics tun keyctl mount_fs timezone

  ctid=$(jq -r ".containers[$index].ctid" "$CONFIG_FILE")
  app=$(jq -r ".containers[$index].app" "$CONFIG_FILE")
  hostname=$(jq -r ".containers[$index].hostname" "$CONFIG_FILE")
  cpu=$(jq -r ".containers[$index].cpu" "$CONFIG_FILE")
  ram=$(jq -r ".containers[$index].ram" "$CONFIG_FILE")
  disk=$(jq -r ".containers[$index].disk" "$CONFIG_FILE")
  bridge=$(jq -r ".containers[$index].bridge" "$CONFIG_FILE")
  ip_cidr=$(jq -r ".containers[$index].ip_cidr" "$CONFIG_FILE")
  gateway=$(jq -r ".containers[$index].gateway" "$CONFIG_FILE")
  vlan=$(jq -r ".containers[$index].vlan" "$CONFIG_FILE")
  mac_address=$(jq -r ".containers[$index].mac_address" "$CONFIG_FILE")
  password=$(jq -r ".containers[$index].password" "$CONFIG_FILE")
  ssh_key=$(jq -r ".containers[$index].ssh_key" "$CONFIG_FILE")
  tags=$(jq -r ".containers[$index].tags" "$CONFIG_FILE")

  gpu=$(jq -r ".containers[$index].gpu // \"no\"" "$CONFIG_FILE")
  unprivileged=$(jq -r ".containers[$index].unprivileged // 1" "$CONFIG_FILE")
  nesting=$(jq -r ".containers[$index].nesting // 1" "$CONFIG_FILE")
  protection=$(jq -r ".containers[$index].protection // \"yes\"" "$CONFIG_FILE")
  nameserver=$(jq -r ".containers[$index].nameserver // .containers[$index].gateway" "$CONFIG_FILE")
  verbose=$(jq -r ".containers[$index].verbose // \"no\"" "$CONFIG_FILE")
  diagnostics=$(jq -r ".containers[$index].diagnostics // \"no\"" "$CONFIG_FILE")
  tun=$(jq -r ".containers[$index].tun // \"no\"" "$CONFIG_FILE")
  keyctl=$(jq -r ".containers[$index].keyctl // 0" "$CONFIG_FILE")
  mount_fs=$(jq -r ".containers[$index].mount_fs // \"nfs,cifs\"" "$CONFIG_FILE")
  timezone=$(jq -r ".containers[$index].timezone // \"Pacific/Auckland\"" "$CONFIG_FILE")

  log_info "Deploying container: $hostname ($app, CTID: $ctid)"

  if pct status "$ctid" >/dev/null 2>&1; then
    log_info "Container ID $ctid already exists. Skipping $hostname"
    return 0
  fi

  env \
    TERM="${TERM:-xterm}" \
    mode=default \
    MODE=default \
    CTID="$ctid" \
    var_ctid="$ctid" \
    var_unprivileged="$unprivileged" \
    var_cpu="$cpu" \
    var_ram="$ram" \
    var_disk="$disk" \
    var_hostname="$hostname" \
    var_brg="$bridge" \
    var_net="$ip_cidr" \
    var_gateway="$gateway" \
    var_vlan="$vlan" \
    var_mac="$mac_address" \
    var_ns="$nameserver" \
    var_ssh=yes \
    var_ssh_authorized_key="$ssh_key" \
    var_pw="$password" \
    var_ipv6_method=none \
    var_nesting="$nesting" \
    var_gpu="$gpu" \
    var_protection="$protection" \
    var_tags="$tags;automated" \
    var_verbose="$verbose" \
    var_diagnostics="$diagnostics" \
    var_tun="$tun" \
    var_keyctl="$keyctl" \
    var_mount_fs="$mount_fs" \
    var_timezone="$timezone" \
    bash -c "$(curl -fsSL "${SCRIPT_BASE}/${app}.sh")" _ default

  log_success "Deployed container: $hostname"
}

deploy_single() {
  local target="${1:-0}"

  if [[ "$target" =~ ^[0-9]+$ ]]; then
    deploy_container "$target"
    return
  fi

  local index
  index=$(jq -r --arg hostname "$target" '
    .containers
    | to_entries[]
    | select(.value.hostname == $hostname)
    | .key
  ' "$CONFIG_FILE" | head -n 1)

  [ -n "$index" ] || {
    log_error "No container found with hostname: $target"
    exit 1
  }

  deploy_container "$index"
}

deploy_all() {
  local container_count
  container_count=$(jq '.containers | length' "$CONFIG_FILE")

  log_info "Deploying $container_count containers sequentially"

  for index in $(seq 0 $((container_count - 1))); do
    deploy_container "$index"
    sleep 5
  done
}

deploy_parallel() {
  local container_count running_jobs
  container_count=$(jq '.containers | length' "$CONFIG_FILE")
  running_jobs=0

  log_info "Deploying $container_count containers in parallel with $PARALLEL_JOBS jobs"

  for index in $(seq 0 $((container_count - 1))); do
    (
      deploy_container "$index" || log_error "Deployment failed for config index $index"
    ) &

    running_jobs=$((running_jobs + 1))

    if [ "$running_jobs" -ge "$PARALLEL_JOBS" ]; then
      wait -n || true
      running_jobs=$((running_jobs - 1))
    fi
  done

  wait || true
}

deploy_parallel_by_app() {
  local target_app="$1"
  local running_jobs=0

  log_info "Deploying containers for app '$target_app' in parallel with $PARALLEL_JOBS jobs"

  while read -r index; do
    (
      deploy_container "$index" || log_error "Deployment failed for config index $index"
    ) &

    running_jobs=$((running_jobs + 1))

    if [ "$running_jobs" -ge "$PARALLEL_JOBS" ]; then
      wait -n || true
      running_jobs=$((running_jobs - 1))
    fi
  done < <(
    jq -r --arg app "$target_app" '
      .containers
      | to_entries[]
      | select(.value.app == $app)
      | .key
    ' "$CONFIG_FILE"
  )

  wait || true
}

generate_report() {
  log_info "Generating deployment report"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "DEPLOYMENT REPORT"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "Time: $(date)"
  echo ""
  pct list
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
  local action="${1:-single}"
  local target="${2:-0}"

  setup_logging
  log_info "Starting Proxmox deployment system"
  validate_prerequisites
  validate_config

  case "$action" in
    single)
      deploy_single "$target"
      ;;
    all)
      deploy_all
      ;;
    parallel)
      deploy_parallel
      ;;
    parallel-app)
      deploy_parallel_by_app "$target"
      ;;
    *)
      log_error "Usage: $0 single [index|hostname] | all | parallel | parallel-app [app]"
      exit 1
      ;;
  esac

  generate_report
  log_success "Deployment complete"
  exit
}

main "$@"

#_____________________________________________________________________________________________________________________________
# Notes
#
# Copy files to Proxmox Server:
# scp production-deploy.sh deployment-config.json root@192.168.20.10:/root/
#
# Run one container:
# ssh -tt root@192.168.20.10 'export TERM=xterm; /root/production-deploy.sh single dns01'
#
# Run only Plex containers in parallel:
# ssh -tt root@192.168.20.10 'export TERM=xterm; PARALLEL_JOBS=2 /root/production-deploy.sh parallel-app plex'
#
# Run only Technitium DNS containers in parallel:
# ssh -tt root@192.168.20.10 'export TERM=xterm; PARALLEL_JOBS=2 /root/production-deploy.sh parallel-app technitiumdns'
#
# Run all containers in parallel:
# ssh -tt root@192.168.20.10 'export TERM=xterm; PARALLEL_JOBS=3 /root/production-deploy.sh parallel'
#
# Run all containers sequentially:
# ssh -tt root@192.168.20.10 'export TERM=xterm; /root/production-deploy.sh all'
#
# Cleanup:
# rm /root/production-deploy.sh
# rm /root/deployment-config.json
#_____________________________________________________________________________________________________________________________