#!/usr/bin/env python3
"""
# ==============================================================================
# File: scripts/lib/terraform-lxc-secret-manager.py
# Purpose:
#   Prepare Terraform LXC password secrets from container password_key values.
# Notes:
#   - The committed containers.auto.tfvars.json file stores password key names only.
#   - Actual password values are stored in state/secrets/passwords/passwords.enc.env.
#   - This script writes the local-only secrets.auto.tfvars.json bridge file.
#   - Password values are never printed.
# ==============================================================================
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ASSIGNMENT_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def load_containers(tfvars_file: Path) -> dict[str, dict[str, object]]:
    if not tfvars_file.is_file():
        raise SystemExit(f"ERROR: Missing Terraform LXC tfvars file: {tfvars_file}")
    try:
        data = json.loads(tfvars_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: Invalid JSON in {tfvars_file}: {exc}") from exc

    containers = data.get("containers")
    if not isinstance(containers, dict) or not containers:
        raise SystemExit(f"ERROR: No containers object found in {tfvars_file}.")

    valid_containers: dict[str, dict[str, object]] = {}
    for name, values in containers.items():
        if isinstance(values, dict):
            valid_containers[str(name)] = values
    if not valid_containers:
        raise SystemExit(f"ERROR: No valid container definitions found in {tfvars_file}.")
    return valid_containers


def required_password_keys(containers: dict[str, dict[str, object]]) -> list[str]:
    keys: list[str] = []
    for container_name in sorted(containers):
        password_key = str(containers[container_name].get("password_key") or "").strip()
        if not password_key:
            raise SystemExit(f"ERROR: Container {container_name} is missing password_key.")
        if not ENV_KEY_PATTERN.match(password_key):
            raise SystemExit(f"ERROR: Container {container_name} has invalid password_key: {password_key}")
        if password_key not in keys:
            keys.append(password_key)
    return keys


def parse_dotenv_value(raw_value: str) -> str:
    try:
        parsed = shlex.split("x=" + raw_value, posix=True)
    except ValueError:
        return raw_value.strip().strip('"').strip("'")
    if not parsed:
        return ""
    first = parsed[0]
    return first.split("=", 1)[1] if "=" in first else ""


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ASSIGNMENT_PATTERN.match(stripped)
        if match:
            values[match.group(1)] = parse_dotenv_value(match.group(2))
    return values


def dotenv_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def decrypt_password_file(password_file: Path, age_key_file: Path | None) -> str:
    if not password_file.is_file():
        raise SystemExit(f"ERROR: Missing encrypted password file: {password_file}\nRun: task passwords:encrypt")
    if shutil.which("sops") is None:
        raise SystemExit("ERROR: sops is not installed. Run: task passwords:install")

    env = os.environ.copy()
    if age_key_file and age_key_file.is_file():
        env["SOPS_AGE_KEY_FILE"] = str(age_key_file)

    command = ["sops", "--decrypt", "--input-type", "dotenv", "--output-type", "dotenv", str(password_file)]
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise SystemExit("ERROR: Could not decrypt password file with SOPS. Check the age key and SOPS config.")
    return result.stdout


def encrypt_password_text(text: str, password_file: Path, recipients_file: Path, age_key_file: Path | None) -> None:
    if shutil.which("sops") is None:
        raise SystemExit("ERROR: sops is not installed. Run: task passwords:install")
    if not recipients_file.is_file():
        raise SystemExit(f"ERROR: Missing SOPS recipients file: {recipients_file}\nRun: task passwords:keys:generate")

    recipient_lines = [line.strip() for line in recipients_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    recipient = recipient_lines[0] if recipient_lines else ""
    if not recipient:
        raise SystemExit(f"ERROR: Empty SOPS recipients file: {recipients_file}")

    env = os.environ.copy()
    if age_key_file and age_key_file.is_file():
        env["SOPS_AGE_KEY_FILE"] = str(age_key_file)

    password_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".env", delete=False) as runtime_file:
        runtime_file.write(text)
        runtime_path = Path(runtime_file.name)
    os.chmod(runtime_path, 0o600)

    try:
        command = [
            "sops",
            "--encrypt",
            "--age",
            recipient,
            "--input-type",
            "dotenv",
            "--output-type",
            "dotenv",
            "--filename-override",
            str(password_file),
            str(runtime_path),
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            message = "ERROR: Could not encrypt updated password file with SOPS."
            if detail:
                message = f"{message}\n{detail}"
            raise SystemExit(message)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(password_file.parent)) as encrypted_file:
            encrypted_file.write(result.stdout)
            encrypted_path = Path(encrypted_file.name)
        os.chmod(encrypted_path, 0o600)
        encrypted_path.replace(password_file)
    finally:
        runtime_path.unlink(missing_ok=True)


def append_missing_passwords(existing_text: str, missing_keys: list[str], prompt: bool) -> tuple[str, dict[str, str]]:
    new_values: dict[str, str] = {}
    if not missing_keys:
        return existing_text, new_values
    if not prompt:
        missing_list = ", ".join(missing_keys)
        raise SystemExit(f"ERROR: Missing LXC password values: {missing_list}")

    lines = existing_text.splitlines()
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("# Terraform LXC root passwords")

    for key in missing_keys:
        while True:
            value = getpass.getpass(f"What is the root password to use ({key}): ")
            if value:
                break
            print("Password cannot be blank.", file=sys.stderr)
        lines.append(f"{key}={dotenv_quote(value)}")
        new_values[key] = value

    return "\n".join(lines) + "\n", new_values


def write_secret_tfvars(output_file: Path, password_values: dict[str, str], required_keys: list[str]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"container_passwords": {key: password_values[key] for key in required_keys}}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(output_file.parent)) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        tmp_path = Path(handle.name)
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(output_file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Terraform LXC password secrets.")
    parser.add_argument("--containers-file", required=True, type=Path)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--recipients-file", required=True, type=Path)
    parser.add_argument("--age-key-file", required=True, type=Path)
    parser.add_argument("--output-file", required=True, type=Path)
    parser.add_argument("--prompt-missing", action="store_true")
    args = parser.parse_args()

    containers = load_containers(args.containers_file)
    required_keys = required_password_keys(containers)

    password_text = decrypt_password_file(args.password_file, args.age_key_file)
    password_values = parse_dotenv(password_text)

    missing_keys = [key for key in required_keys if not password_values.get(key)]
    updated_text, new_values = append_missing_passwords(password_text, missing_keys, args.prompt_missing)
    if new_values:
        encrypt_password_text(updated_text, args.password_file, args.recipients_file, args.age_key_file)
        password_values.update(new_values)

    still_missing = [key for key in required_keys if not password_values.get(key)]
    if still_missing:
        missing_list = ", ".join(still_missing)
        raise SystemExit(f"ERROR: Missing LXC password values after preparation: {missing_list}")

    write_secret_tfvars(args.output_file, password_values, required_keys)
    print(f"Prepared Terraform LXC secrets for {len(required_keys)} password key(s): {args.output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
