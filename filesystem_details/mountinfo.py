#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure read-only mount topology helpers for Filesystem Details."""

import os
import re
from pathlib import Path

_ESCAPE_RE = re.compile(r"\\([0-7]{3})")

NETWORK_FS_TYPES = {
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs",
    "9p", "ceph", "glusterfs", "afs",
}

VIRTUAL_FS_TYPES = {
    "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
    "pstore", "securityfs", "debugfs", "tracefs", "configfs", "mqueue",
    "hugetlbfs", "fusectl", "binfmt_misc", "autofs", "overlay", "ramfs",
    "efivarfs", "bpf", "nsfs",
}


def decode_mount_field(value):
    """Decode the octal escapes used by procfs mount records."""
    return _ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 8)), str(value))


def _option_value(options, key):
    prefix = key + "="
    for item in options or []:
        if item.startswith(prefix):
            return decode_mount_field(item[len(prefix):])
    return ""


def parse_mountinfo_line(line):
    """Parse one /proc/*/mountinfo record according to proc_pid_mountinfo(5)."""
    fields = line.rstrip("\n").split()
    if "-" not in fields:
        return None
    separator = fields.index("-")
    if separator < 6 or len(fields) < separator + 4:
        return None

    mount_options = fields[5].split(",") if fields[5] else []
    optional_fields = fields[6:separator]
    super_options = fields[separator + 3].split(",") if fields[separator + 3] else []

    record = {
        "mount_id": fields[0],
        "parent_id": fields[1],
        "major_minor": fields[2],
        "root": decode_mount_field(fields[3]),
        "mount_point": decode_mount_field(fields[4]),
        "mount_options": mount_options,
        "optional_fields": optional_fields,
        "fstype": decode_mount_field(fields[separator + 1]),
        "source": decode_mount_field(fields[separator + 2]),
        "super_options": super_options,
    }

    access = "RO" if "ro" in mount_options else ("RW" if "rw" in mount_options else "Not reported")
    record["access"] = access

    propagation = {}
    for field in optional_fields:
        if field == "unbindable":
            propagation["unbindable"] = "Yes"
        elif ":" in field:
            key, value = field.split(":", 1)
            if key in {"shared", "master", "propagate_from"}:
                propagation[key] = value
    record["propagation"] = propagation

    if record["fstype"].lower() == "btrfs":
        combined_options = list(mount_options) + list(super_options)
        record["btrfs_subvol"] = _option_value(combined_options, "subvol")
        record["btrfs_subvolid"] = _option_value(combined_options, "subvolid")
    else:
        record["btrfs_subvol"] = ""
        record["btrfs_subvolid"] = ""

    return record


def classify_mount(record):
    """Conservative mount classification; unknown is never guessed as virtual."""
    fstype = str(record.get("fstype", "")).lower()
    source = str(record.get("source", ""))
    major_minor = str(record.get("major_minor", ""))

    if fstype in NETWORK_FS_TYPES:
        return "Network / Remote"
    if fstype in VIRTUAL_FS_TYPES:
        return "Virtual / Pseudo"
    if source.startswith("/dev/"):
        return "Local / Storage"
    try:
        major = int(major_minor.split(":", 1)[0])
    except Exception:
        major = 0
    if major > 0:
        return "Local / Storage"
    return "Other / Unclassified"


def read_mountinfo(path="/proc/self/mountinfo"):
    records = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            record = parse_mountinfo_line(raw)
            if record is None:
                continue
            record["category"] = classify_mount(record)
            records.append(record)

    by_id = {record["mount_id"]: record for record in records}
    children = {}
    for record in records:
        children.setdefault(record["parent_id"], []).append(record["mount_id"])

    source_groups = {}
    device_groups = {}
    for record in records:
        source_groups.setdefault(record["source"], []).append(record["mount_id"])
        device_groups.setdefault(record["major_minor"], []).append(record["mount_id"])

    for record in records:
        parent = by_id.get(record["parent_id"])
        record["parent_mount_point"] = parent["mount_point"] if parent else ""
        record["child_mount_points"] = [
            by_id[mid]["mount_point"] for mid in children.get(record["mount_id"], [])
            if mid in by_id
        ]
        record["same_source_mount_points"] = [
            by_id[mid]["mount_point"] for mid in source_groups.get(record["source"], [])
            if mid in by_id and mid != record["mount_id"]
        ]
        record["same_device_mount_points"] = [
            by_id[mid]["mount_point"] for mid in device_groups.get(record["major_minor"], [])
            if mid in by_id and mid != record["mount_id"]
        ]

    return records


def mount_namespace_identity(path="/proc/self/ns/mnt"):
    try:
        return os.readlink(path)
    except OSError:
        return "Unavailable"


def statvfs_details(mount_point):
    """Return filesystem capacity/limits exactly from os.statvfs()."""
    st = os.statvfs(mount_point)
    fragment_size = st.f_frsize or st.f_bsize or 1

    total_bytes = fragment_size * st.f_blocks
    free_bytes = fragment_size * st.f_bfree
    available_bytes = fragment_size * st.f_bavail
    used_bytes = max(0, total_bytes - free_bytes)
    unavailable_to_ordinary = max(0, free_bytes - available_bytes)
    used_percent = (used_bytes / total_bytes * 100.0) if total_bytes else 0.0

    return {
        "block_size": int(st.f_bsize),
        "fragment_size": int(st.f_frsize),
        "blocks_total": int(st.f_blocks),
        "blocks_free": int(st.f_bfree),
        "blocks_available": int(st.f_bavail),
        "total_bytes": int(total_bytes),
        "used_bytes": int(used_bytes),
        "free_bytes": int(free_bytes),
        "available_bytes": int(available_bytes),
        "unavailable_to_ordinary_bytes": int(unavailable_to_ordinary),
        "used_percent": float(used_percent),
        "inodes_total": int(st.f_files),
        "inodes_free": int(st.f_ffree),
        "inodes_available": int(st.f_favail),
        "max_filename_length": int(st.f_namemax),
        "flags": int(st.f_flag),
    }


def format_bytes(value):
    value = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value):,} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
