#!/usr/bin/env bash
# ==============================================================================
# File: scripts/lib/health-check.sh
# Purpose:
#   Shared health and audit output helpers for homelab Taskfiles.
# Notes:
#   - Source this file from Taskfile shell blocks.
#   - Do not print secret values through these helpers.
# ==============================================================================


health_heading() {
  local title="$1"
  local underline=""
  local index=0

  while [[ "$index" -lt "${#title}" ]]; do
    underline="${underline}-"
    index=$((index + 1))
  done

  printf '\n%s\n' "$title"
  printf '%s\n' "$underline"
}

health_status() {
  local status="$1"
  local label="$2"
  local detail="${3:-}"

  if [[ -n "$detail" ]]; then
    printf '%-10s %s: %s\n' "[$status]" "$label" "$detail"
  else
    printf '%-10s %s\n' "[$status]" "$label"
  fi
}

health_ok() { health_status "OK" "$1" "${2:-}"; }
health_missing() { health_status "MISSING" "$1" "${2:-}"; }
health_warn() { health_status "WARN" "$1" "${2:-}"; }
health_fail() { health_status "FAIL" "$1" "${2:-}"; }
health_skip() { health_status "SKIPPED" "$1" "${2:-}"; }

health_command() {
  local label="$1"
  local command_name="$2"
  shift 2

  if command -v "$command_name" >/dev/null 2>&1; then
    local output
    output="$($@ 2>/dev/null | head -n 1 || true)"
    health_ok "$label" "${output:-installed}"
  else
    health_missing "$label" "$command_name not found"
  fi
}

health_file() {
  local label="$1"
  local file_path="$2"

  if [[ -f "$file_path" ]]; then
    health_ok "$label" "$file_path"
  else
    health_missing "$label" "$file_path"
  fi
}
