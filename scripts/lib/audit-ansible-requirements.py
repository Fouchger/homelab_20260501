#!/usr/bin/env python3
"""
File: scripts/lib/audit-ansible-requirements.py
Purpose:
  Print collection or role names from ansible/requirements.yml without requiring PyYAML.
Notes:
  This parser is intentionally small and only supports the simple requirements.yml
  structure used by this repository.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def iter_names(requirements_file: Path, section_name: str):
    current_section: str | None = None
    for raw_line in requirements_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        if line == "collections:":
            current_section = "collections"
            continue
        if line == "roles:":
            current_section = "roles"
            continue
        if current_section == section_name and line.startswith("- name:"):
            yield line.split(":", 1)[1].strip().strip('"').strip("'")


def main() -> int:
    parser = argparse.ArgumentParser(description="List names from ansible/requirements.yml")
    parser.add_argument("section", choices=["collections", "roles"])
    parser.add_argument("requirements_file")
    args = parser.parse_args()

    requirements_file = Path(args.requirements_file)
    if not requirements_file.exists():
        print(f"Missing requirements file: {requirements_file}")
        return 1

    for name in iter_names(requirements_file, args.section):
        print(name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
