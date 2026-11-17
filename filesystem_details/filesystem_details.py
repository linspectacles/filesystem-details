#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only selected-filesystem structural providers for Filesystem Details.

The providers deliberately inspect only the filesystem represented by a selected
mount record.  They never parse raw block devices and never perform mutating
filesystem operations.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import re
import struct
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# Linux ioctl helpers
# ---------------------------------------------------------------------------

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction, type_value, nr, size):
    if isinstance(type_value, str):
        type_value = ord(type_value)
    return (
        (int(direction) << _IOC_DIRSHIFT)
        | (int(type_value) << _IOC_TYPESHIFT)
        | (int(nr) << _IOC_NRSHIFT)
        | (int(size) << _IOC_SIZESHIFT)
    )


def _ior(type_value, nr, ctype):
    return _ioc(_IOC_READ, type_value, nr, ctypes.sizeof(ctype))


def _iowr(type_value, nr, ctype):
    return _ioc(_IOC_READ | _IOC_WRITE, type_value, nr, ctypes.sizeof(ctype))


def _ioctl_struct(fd, command, ctype):
    raw = bytearray(ctypes.sizeof(ctype))
    obj = ctype.from_buffer(raw)
    fcntl.ioctl(fd, command, raw, True)
    return obj, raw


def _uuid_text(raw):
    try:
        return str(uuid.UUID(bytes=bytes(raw)))
    except Exception:
        return bytes(raw).hex()


def _read_text(path, max_bytes=1024 * 1024):
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(max_bytes).strip(), "ok"
    except FileNotFoundError:
        return "", "unavailable"
    except PermissionError:
        return "", "access denied"
    except OSError as exc:
        return "", f"read error: {exc}"


def _open_mountpoint(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return os.open(path, flags)


def _device_name(record):
    """Resolve an ext4 runtime-provider name from the mount source only.

    This deliberately avoids /sys/class/block and /sys/dev/block: Mounted
    Filesystems must not grow a block-topology dependency merely to deepen a
    selected filesystem.  Device-mapper aliases normally resolve through the
    /dev symlink to the kernel name required by /sys/fs/ext4 and /proc/fs/ext4.
    """
    source = str(record.get("source", ""))
    if source.startswith("/dev/"):
        try:
            resolved = os.path.realpath(source)
            name = os.path.basename(resolved)
            if name:
                return name
        except OSError:
            pass
        return os.path.basename(source)
    return ""


# ---------------------------------------------------------------------------
# ext4
# ---------------------------------------------------------------------------

_EXT4_SYSFS_READ_FIELDS = (
    "delayed_allocation_blocks",
    "lifetime_write_kbytes",
    "session_write_kbytes",
    "extent_max_zeroout_kb",
    "inode_readahead_blks",
    "mb_group_prealloc",
    "mb_max_to_scan",
    "mb_min_to_scan",
    "mb_order2_req",
    "mb_stream_req",
    "reserved_clusters",
    "warning_ratelimit_ms",
)


def _parse_ext4_mb_groups(text):
    """Parse /proc/fs/ext4/<dev>/mb_groups conservatively.

    Kernel versions have varied the header slightly.  Preserve raw values and
    map the well-known leading columns only when their positions are clear.
    """
    rows = []
    labels = []
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#group"):
            before_bracket = line.split("[", 1)[0]
            tail = before_bracket.split(":", 1)[1] if ":" in before_bracket else ""
            labels = [token.strip().lower() for token in tail.split() if token.strip()]
            # Some historical kernels printed duplicate "free" labels.  Keep
            # the second distinct rather than overwriting it.
            seen = {}
            normalized = []
            for label in labels:
                count = seen.get(label, 0)
                seen[label] = count + 1
                normalized.append(label if count == 0 else f"{label}_{count + 1}")
            labels = normalized
            continue
        match = re.match(r"^#?\s*(\d+)\s*:\s*(.*?)\s*\[\s*(.*?)\s*\]\s*$", line)
        if not match:
            continue
        group = int(match.group(1))
        leading = [int(value) for value in re.findall(r"-?\d+", match.group(2))]
        buddies = [int(value) for value in re.findall(r"-?\d+", match.group(3))]
        fields = {}
        for index, value in enumerate(leading):
            key = labels[index] if index < len(labels) else f"field_{index + 1}"
            fields[key] = value

        # Well-known columns, with positional fallback for old kernels.
        free_blocks = fields.get("free", leading[0] if len(leading) > 0 else None)
        fragments = fields.get("frags", leading[1] if len(leading) > 1 else None)
        first_free = fields.get("first", leading[2] if len(leading) > 2 else None)
        prealloc = fields.get("pa", leading[3] if len(leading) > 3 else None)
        largest_order = None
        for order, count in enumerate(buddies):
            if count > 0:
                largest_order = order
        row = {
            "group": group,
            "free_blocks": free_blocks,
            "fragments": fragments,
            "first_free": first_free,
            "prealloc_chunks": prealloc,
            "largest_free_order": largest_order,
            "largest_free_blocks": (1 << largest_order) if largest_order is not None else 0,
            "buddy_counts": buddies,
            "raw_fields": fields,
        }
        rows.append(row)
    return rows


def inspect_ext4(record):
    dev = _device_name(record)
    result = {
        "provider": "ext4",
        "device_name": dev or "Unavailable",
        "summary": {},
        "allocation_columns": [
            ("group", "Group"),
            ("free_blocks", "Free Blocks"),
            ("fragments", "Fragments"),
            ("first_free", "First Free"),
            ("prealloc_chunks", "Preallocated Chunks"),
            ("largest_free_order", "Largest Free Order"),
            ("largest_free_blocks", "Largest Free Blocks"),
        ],
        "allocation": [],
        "source_status": {},
    }
    if not dev:
        result["source_status"]["device"] = "kernel device name unavailable"
        return result

    proc_dir = Path("/proc/fs/ext4") / dev
    sys_dir = Path("/sys/fs/ext4") / dev
    result["summary"]["Kernel Device Name"] = dev

    for field in _EXT4_SYSFS_READ_FIELDS:
        text, state = _read_text(sys_dir / field, max_bytes=64 * 1024)
        if state == "ok":
            result["summary"][field] = text
    result["source_status"][str(sys_dir)] = "available" if sys_dir.is_dir() else "unavailable"

    mb_text, state = _read_text(proc_dir / "mb_groups", max_bytes=32 * 1024 * 1024)
    result["source_status"][str(proc_dir / "mb_groups")] = state
    if state == "ok":
        result["allocation"] = _parse_ext4_mb_groups(mb_text)
        result["summary"]["Allocator Groups Reported"] = len(result["allocation"])
    return result


# ---------------------------------------------------------------------------
# XFS
# ---------------------------------------------------------------------------

class XfsFsopGeom(ctypes.Structure):
    _fields_ = [
        ("blocksize", ctypes.c_uint32),
        ("rtextsize", ctypes.c_uint32),
        ("agblocks", ctypes.c_uint32),
        ("agcount", ctypes.c_uint32),
        ("logblocks", ctypes.c_uint32),
        ("sectsize", ctypes.c_uint32),
        ("inodesize", ctypes.c_uint32),
        ("imaxpct", ctypes.c_uint32),
        ("datablocks", ctypes.c_uint64),
        ("rtblocks", ctypes.c_uint64),
        ("rtextents", ctypes.c_uint64),
        ("logstart", ctypes.c_uint64),
        ("uuid", ctypes.c_ubyte * 16),
        ("sunit", ctypes.c_uint32),
        ("swidth", ctypes.c_uint32),
        ("version", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("logsectsize", ctypes.c_uint32),
        ("rtsectsize", ctypes.c_uint32),
        ("dirblocksize", ctypes.c_uint32),
        ("logsunit", ctypes.c_uint32),
        ("sick", ctypes.c_uint32),
        ("checked", ctypes.c_uint32),
        ("rgextents", ctypes.c_uint32),
        ("rgcount", ctypes.c_uint32),
        ("rtstart", ctypes.c_uint64),
        ("rtreserved", ctypes.c_uint64),
        ("reserved", ctypes.c_uint64 * 14),
    ]


class XfsAgGeometry(ctypes.Structure):
    _fields_ = [
        ("ag_number", ctypes.c_uint32),
        ("ag_length", ctypes.c_uint32),
        ("ag_freeblks", ctypes.c_uint32),
        ("ag_icount", ctypes.c_uint32),
        ("ag_ifree", ctypes.c_uint32),
        ("ag_sick", ctypes.c_uint32),
        ("ag_checked", ctypes.c_uint32),
        ("ag_flags", ctypes.c_uint32),
        ("ag_reserved", ctypes.c_uint64 * 12),
    ]


XFS_IOC_FSGEOMETRY = _ior("X", 126, XfsFsopGeom)
XFS_IOC_AG_GEOMETRY = _iowr("X", 61, XfsAgGeometry)

_XFS_AG_HEALTH = (
    (1 << 0, "Superblock"),
    (1 << 1, "AGF Header"),
    (1 << 2, "AGFL Header"),
    (1 << 3, "AGI Header"),
    (1 << 4, "Free Space by Block"),
    (1 << 5, "Free Space by Length"),
    (1 << 6, "Inode Index"),
    (1 << 7, "Free Inode Index"),
    (1 << 8, "Reverse Mappings"),
    (1 << 9, "Reference Counts"),
    (1 << 10, "Inodes"),
)

_XFS_FS_HEALTH = (
    (1 << 0, "Summary Counters"),
    (1 << 1, "User Quota"),
    (1 << 2, "Group Quota"),
    (1 << 3, "Project Quota"),
    (1 << 4, "Realtime Bitmap"),
    (1 << 5, "Realtime Summary"),
    (1 << 6, "Quota Counts"),
    (1 << 7, "Inode Link Counts"),
    (1 << 8, "Metadata Directory"),
    (1 << 9, "Metadata Path"),
)


def _mask_names(mask, mapping):
    raw = int(mask)
    names = [name for bit, name in mapping if raw & bit]
    known = 0
    for bit, _name in mapping:
        known |= int(bit)
    unknown = raw & ~known
    if unknown:
        names.append(f"Unknown reported bits 0x{unknown:x}")
    return names


def _health_state(checked, sick, mapping):
    checked_raw = int(checked)
    sick_raw = int(sick)
    checked_names = _mask_names(checked_raw, mapping)
    sick_names = _mask_names(sick_raw, mapping)
    # State is based on the raw bitsets, not only bits this build knows how to
    # name, so future kernel flags cannot be silently treated as healthy.
    if sick_raw:
        state = "Reported sick"
    elif checked_raw:
        state = "Checked; no reported sickness in checked components"
    else:
        state = "Unchecked / no conclusion"
    return state, checked_names, sick_names


def inspect_xfs(record):
    result = {
        "provider": "XFS",
        "summary": {},
        "allocation_columns": [
            ("ag", "AG"),
            ("length", "Length"),
            ("free_blocks", "Free Blocks"),
            ("inodes", "Inodes"),
            ("free_inodes", "Free Inodes"),
            ("state", "Structural State"),
            ("checked", "Checked"),
            ("sick", "Sick"),
        ],
        "allocation": [],
        "source_status": {},
    }
    mount_point = str(record.get("mount_point", ""))
    try:
        fd = _open_mountpoint(mount_point)
    except OSError as exc:
        result["source_status"]["XFS filesystem fd"] = f"open error: {exc}"
        return result
    try:
        raw = bytearray(ctypes.sizeof(XfsFsopGeom))
        geom = XfsFsopGeom.from_buffer(raw)
        fcntl.ioctl(fd, XFS_IOC_FSGEOMETRY, raw, True)
        result["source_status"]["XFS_IOC_FSGEOMETRY"] = "ok"
        fs_state, checked_names, sick_names = _health_state(
            geom.checked, geom.sick, _XFS_FS_HEALTH
        )
        result["summary"].update({
            "Filesystem UUID": _uuid_text(geom.uuid),
            "Block Size": int(geom.blocksize),
            "Data Sector Size": int(geom.sectsize),
            "Inode Size": int(geom.inodesize),
            "Allocation Groups": int(geom.agcount),
            "Blocks per AG": int(geom.agblocks),
            "Data Blocks": int(geom.datablocks),
            "Log Blocks": int(geom.logblocks),
            "Log Start": int(geom.logstart),
            "Directory Block Size": int(geom.dirblocksize),
            "Stripe Unit (fs blocks)": int(geom.sunit),
            "Stripe Width": int(geom.swidth),
            "Feature Flags": f"0x{int(geom.flags):08x}",
            "Reported Structural State": fs_state,
            "Checked Metadata": ", ".join(checked_names) if checked_names else "None reported",
            "Sick Metadata": ", ".join(sick_names) if sick_names else "None reported",
        })

        for agno in range(int(geom.agcount)):
            raw_ag = bytearray(ctypes.sizeof(XfsAgGeometry))
            ag = XfsAgGeometry.from_buffer(raw_ag)
            ag.ag_number = agno
            try:
                fcntl.ioctl(fd, XFS_IOC_AG_GEOMETRY, raw_ag, True)
            except OSError as exc:
                result["allocation"].append({
                    "ag": agno,
                    "length": None,
                    "free_blocks": None,
                    "inodes": None,
                    "free_inodes": None,
                    "state": f"Unavailable: {exc}",
                    "checked": "",
                    "sick": "",
                })
                continue
            state, checked, sick = _health_state(
                ag.ag_checked, ag.ag_sick, _XFS_AG_HEALTH
            )
            result["allocation"].append({
                "ag": int(ag.ag_number),
                "length": int(ag.ag_length),
                "free_blocks": int(ag.ag_freeblks),
                "inodes": int(ag.ag_icount),
                "free_inodes": int(ag.ag_ifree),
                "state": state,
                "checked": ", ".join(checked) if checked else "None reported",
                "sick": ", ".join(sick) if sick else "None reported",
            })
        result["source_status"]["XFS_IOC_AG_GEOMETRY"] = "ok"
    except OSError as exc:
        result["source_status"]["XFS_IOC_FSGEOMETRY"] = f"unavailable: {exc}"
    finally:
        os.close(fd)
    return result


# ---------------------------------------------------------------------------
# Btrfs
# ---------------------------------------------------------------------------

BTRFS_IOCTL_MAGIC = 0x94
BTRFS_FSID_SIZE = 16
BTRFS_DEVICE_PATH_NAME_MAX = 1024


class BtrfsFsInfo(ctypes.Structure):
    _fields_ = [
        ("max_id", ctypes.c_uint64),
        ("num_devices", ctypes.c_uint64),
        ("fsid", ctypes.c_ubyte * 16),
        ("nodesize", ctypes.c_uint32),
        ("sectorsize", ctypes.c_uint32),
        ("clone_alignment", ctypes.c_uint32),
        ("csum_type", ctypes.c_uint16),
        ("csum_size", ctypes.c_uint16),
        ("flags", ctypes.c_uint64),
        ("generation", ctypes.c_uint64),
        ("metadata_uuid", ctypes.c_ubyte * 16),
        ("reserved", ctypes.c_ubyte * 944),
    ]


class BtrfsDevInfo(ctypes.Structure):
    _fields_ = [
        ("devid", ctypes.c_uint64),
        ("uuid", ctypes.c_ubyte * 16),
        ("bytes_used", ctypes.c_uint64),
        ("total_bytes", ctypes.c_uint64),
        ("fsid", ctypes.c_ubyte * 16),
        ("unused", ctypes.c_uint64 * 377),
        ("path", ctypes.c_ubyte * BTRFS_DEVICE_PATH_NAME_MAX),
    ]


class BtrfsSpaceArgsBase(ctypes.Structure):
    _fields_ = [("space_slots", ctypes.c_uint64), ("total_spaces", ctypes.c_uint64)]


class BtrfsSpaceInfo(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("total_bytes", ctypes.c_uint64),
        ("used_bytes", ctypes.c_uint64),
    ]


BTRFS_IOC_SPACE_INFO = _iowr(BTRFS_IOCTL_MAGIC, 20, BtrfsSpaceArgsBase)
BTRFS_IOC_DEV_INFO = _iowr(BTRFS_IOCTL_MAGIC, 30, BtrfsDevInfo)
BTRFS_IOC_FS_INFO = _ior(BTRFS_IOCTL_MAGIC, 31, BtrfsFsInfo)

_BTRFS_CLASS = ((1 << 0, "Data"), (1 << 1, "System"), (1 << 2, "Metadata"))
_BTRFS_PROFILE = (
    (1 << 3, "RAID0"),
    (1 << 4, "RAID1"),
    (1 << 5, "DUP"),
    (1 << 6, "RAID10"),
    (1 << 7, "RAID5"),
    (1 << 8, "RAID6"),
    (1 << 9, "RAID1C3"),
    (1 << 10, "RAID1C4"),
)
_BTRFS_CSUM = {0: "CRC32C", 1: "XXHASH", 2: "SHA256", 3: "BLAKE2"}


def _btrfs_space_info(fd):
    first = bytearray(ctypes.sizeof(BtrfsSpaceArgsBase))
    base = BtrfsSpaceArgsBase.from_buffer(first)
    base.space_slots = 0
    base.total_spaces = 0
    fcntl.ioctl(fd, BTRFS_IOC_SPACE_INFO, first, True)
    total = int(base.total_spaces)
    if total <= 0:
        return []
    total = min(total, 4096)  # defensive bound; normal systems are tiny.
    base_size = ctypes.sizeof(BtrfsSpaceArgsBase)
    info_size = ctypes.sizeof(BtrfsSpaceInfo)
    buf = bytearray(base_size + total * info_size)
    args = BtrfsSpaceArgsBase.from_buffer(buf)
    args.space_slots = total
    args.total_spaces = 0
    fcntl.ioctl(fd, BTRFS_IOC_SPACE_INFO, buf, True)
    count = min(int(args.total_spaces), total)
    rows = []
    for index in range(count):
        info = BtrfsSpaceInfo.from_buffer(buf, base_size + index * info_size)
        classes = [name for bit, name in _BTRFS_CLASS if int(info.flags) & bit]
        profiles = [name for bit, name in _BTRFS_PROFILE if int(info.flags) & bit]
        rows.append({
            "class": " + ".join(classes) if classes else "Other / Reported",
            "profile": " + ".join(profiles) if profiles else "Single / none reported",
            "total_bytes": int(info.total_bytes),
            "used_bytes": int(info.used_bytes),
            "free_bytes": max(0, int(info.total_bytes) - int(info.used_bytes)),
            "flags": f"0x{int(info.flags):016x}",
        })
    return rows


def inspect_btrfs(record):
    result = {
        "provider": "Btrfs",
        "summary": {},
        "devices": [],
        "allocation_columns": [
            ("class", "Class"),
            ("profile", "Profile"),
            ("total_bytes", "Total"),
            ("used_bytes", "Used"),
            ("free_bytes", "Unallocated in Class"),
            ("flags", "Flags"),
        ],
        "allocation": [],
        "source_status": {},
    }
    mount_point = str(record.get("mount_point", ""))
    try:
        fd = _open_mountpoint(mount_point)
    except OSError as exc:
        result["source_status"]["Btrfs filesystem fd"] = f"open error: {exc}"
        return result
    try:
        raw = bytearray(ctypes.sizeof(BtrfsFsInfo))
        info = BtrfsFsInfo.from_buffer(raw)
        # Ask for checksum/generation/metadata UUID if the running kernel knows
        # these flags; older kernels safely ignore unsupported request bits.
        info.flags = (1 << 0) | (1 << 1) | (1 << 2)
        fcntl.ioctl(fd, BTRFS_IOC_FS_INFO, raw, True)
        result["source_status"]["BTRFS_IOC_FS_INFO"] = "ok"
        result["summary"].update({
            "Filesystem UUID": _uuid_text(info.fsid),
            "Devices": int(info.num_devices),
            "Maximum Device ID": int(info.max_id),
            "Node Size": int(info.nodesize),
            "Sector Size": int(info.sectorsize),
            "Clone Alignment": int(info.clone_alignment),
            "Reported FS Info Flags": f"0x{int(info.flags):016x}",
        })
        returned_flags = int(info.flags)
        if returned_flags & (1 << 0):
            result["summary"]["Checksum"] = _BTRFS_CSUM.get(
                int(info.csum_type), f"Type {int(info.csum_type)}"
            )
            result["summary"]["Checksum Size"] = int(info.csum_size)
        if returned_flags & (1 << 1):
            result["summary"]["Generation"] = int(info.generation)
        if returned_flags & (1 << 2):
            result["summary"]["Metadata UUID"] = _uuid_text(info.metadata_uuid)

        # Filesystem-native member devices only.  Stop once all reported
        # devices have been found; device IDs may be sparse.
        found = 0
        max_id = min(int(info.max_id), 65536)
        for devid in range(1, max_id + 1):
            if found >= int(info.num_devices):
                break
            raw_dev = bytearray(ctypes.sizeof(BtrfsDevInfo))
            dev = BtrfsDevInfo.from_buffer(raw_dev)
            dev.devid = devid
            try:
                fcntl.ioctl(fd, BTRFS_IOC_DEV_INFO, raw_dev, True)
            except OSError as exc:
                if exc.errno in {errno.ENODEV, errno.ENOENT, errno.EINVAL}:
                    continue
                result["source_status"][f"BTRFS_IOC_DEV_INFO({devid})"] = f"error: {exc}"
                continue
            found += 1
            path_bytes = bytes(dev.path).split(b"\0", 1)[0]
            result["devices"].append({
                "device_id": int(dev.devid),
                "device_uuid": _uuid_text(dev.uuid),
                "total_bytes": int(dev.total_bytes),
                "bytes_used": int(dev.bytes_used),
                "path": path_bytes.decode("utf-8", errors="replace"),
            })
        result["source_status"]["BTRFS_IOC_DEV_INFO"] = "ok" if found else "no device rows returned"

        try:
            result["allocation"] = _btrfs_space_info(fd)
            result["source_status"]["BTRFS_IOC_SPACE_INFO"] = "ok"
        except OSError as exc:
            result["source_status"]["BTRFS_IOC_SPACE_INFO"] = f"unavailable: {exc}"
    except OSError as exc:
        result["source_status"]["BTRFS_IOC_FS_INFO"] = f"unavailable: {exc}"
    finally:
        os.close(fd)
    return result


# ---------------------------------------------------------------------------
# FS_IOC_GETFSMAP physical map
# ---------------------------------------------------------------------------

class FsMap(ctypes.Structure):
    _fields_ = [
        ("fmr_device", ctypes.c_uint32),
        ("fmr_flags", ctypes.c_uint32),
        ("fmr_physical", ctypes.c_uint64),
        ("fmr_owner", ctypes.c_uint64),
        ("fmr_offset", ctypes.c_uint64),
        ("fmr_length", ctypes.c_uint64),
        ("fmr_reserved", ctypes.c_uint64 * 3),
    ]


class FsMapHead(ctypes.Structure):
    _fields_ = [
        ("fmh_iflags", ctypes.c_uint32),
        ("fmh_oflags", ctypes.c_uint32),
        ("fmh_count", ctypes.c_uint32),
        ("fmh_entries", ctypes.c_uint32),
        ("fmh_reserved", ctypes.c_uint64 * 6),
        ("fmh_keys", FsMap * 2),
    ]


FS_IOC_GETFSMAP = _iowr("X", 59, FsMapHead)
FMR_OF_PREALLOC = 0x1
FMR_OF_ATTR_FORK = 0x2
FMR_OF_EXTENT_MAP = 0x4
FMR_OF_SHARED = 0x8
FMR_OF_SPECIAL_OWNER = 0x10
FMR_OF_LAST = 0x20
FMH_OF_DEV_T = 0x1
FMR_OWN_FREE = 1
FMR_OWN_UNKNOWN = 2
FMR_OWN_METADATA = 3

# FS_IOC_GETFSMAP special owners are interpreted in the context of the
# selected filesystem.  ext4 deliberately shares some FMR_OWNER('X', n)
# identifiers with XFS, but they must not be shown as XFS-owned records.
_EXT4_SPECIAL_OWNERS = {
    (ord("X") << 32) | 1: "ext4 Filesystem Metadata",
    (ord("X") << 32) | 2: "ext4 Journal Log",
    (ord("X") << 32) | 5: "ext4 Inodes",
    (ord("f") << 32) | 1: "ext4 Group Descriptors",
    (ord("f") << 32) | 2: "ext4 Reserved Group Descriptors",
    (ord("f") << 32) | 3: "ext4 Block Bitmap",
    (ord("f") << 32) | 4: "ext4 Inode Bitmap",
}

_XFS_SPECIAL_OWNERS = {
    (ord("X") << 32) | 1: "XFS Filesystem Metadata",
    (ord("X") << 32) | 2: "XFS Journal Log",
    (ord("X") << 32) | 3: "XFS Allocation-Group Metadata",
    (ord("X") << 32) | 4: "XFS Inode Btree",
    (ord("X") << 32) | 5: "XFS Inodes",
    (ord("X") << 32) | 6: "XFS Reference-Count Tree",
    (ord("X") << 32) | 7: "XFS CoW Staging",
    (ord("X") << 32) | 8: "XFS Defective Blocks",
}


def _fsmap_owner(owner, flags, fstype):
    owner = int(owner)
    if not (int(flags) & FMR_OF_SPECIAL_OWNER):
        return str(owner)
    if owner == FMR_OWN_FREE:
        return "Free Space"
    if owner == FMR_OWN_UNKNOWN:
        return "Unknown Owner"
    if owner == FMR_OWN_METADATA:
        return "Filesystem Metadata"
    special_owners = {
        "ext4": _EXT4_SPECIAL_OWNERS,
        "xfs": _XFS_SPECIAL_OWNERS,
    }.get(str(fstype).lower(), {})
    return special_owners.get(owner, f"Special Owner 0x{owner:016x}")


def _fsmap_flags(flags):
    names = []
    flags = int(flags)
    for bit, name in (
        (FMR_OF_PREALLOC, "Preallocated"),
        (FMR_OF_ATTR_FORK, "Attribute Fork"),
        (FMR_OF_EXTENT_MAP, "Extent Map"),
        (FMR_OF_SHARED, "Shared"),
        (FMR_OF_SPECIAL_OWNER, "Special Owner"),
        (FMR_OF_LAST, "Last"),
    ):
        if flags & bit:
            names.append(name)
    return ", ".join(names) if names else "None reported"


def filesystem_map(record, max_records=100000, batch_size=256):
    """Retrieve a read-only FS_IOC_GETFSMAP snapshot for the selected mount."""
    mount_point = str(record.get("mount_point", ""))
    fstype = str(record.get("fstype", "")).lower()
    rows = []
    status = {"source": "FS_IOC_GETFSMAP", "truncated": False, "error": ""}

    # The deep Btrfs allocation provider does not imply support for GETFSMAP.
    # Check the filesystem type before opening the mount or issuing an ioctl.
    if fstype == "btrfs":
        status["error"] = (
            "Btrfs does not expose FS_IOC_GETFSMAP. "
            "Summary and Allocation inspection remain available."
        )
        return rows, status
    if fstype not in {"ext4", "xfs"}:
        status["error"] = (
            f"FS_IOC_GETFSMAP is not supported for filesystem type {fstype or 'unknown'} "
            "in this inspector."
        )
        return rows, status

    try:
        fd = _open_mountpoint(mount_point)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EPERM}:
            status["error"] = "Permission denied opening the selected mount for physical mapping."
        else:
            status["error"] = f"Cannot open the selected mount: {exc}"
        return rows, status
    try:
        head_size = ctypes.sizeof(FsMapHead)
        rec_size = ctypes.sizeof(FsMap)
        low_key_bytes = bytes(rec_size)
        # The high key spans the full documented fsmap keyspace, but reserved
        # fields must remain zero or the kernel may reject the request.
        high_key = FsMap()
        high_key.fmr_device = 0xFFFFFFFF
        high_key.fmr_flags = 0xFFFFFFFF
        high_key.fmr_physical = 0xFFFFFFFFFFFFFFFF
        high_key.fmr_owner = 0xFFFFFFFFFFFFFFFF
        high_key.fmr_offset = 0xFFFFFFFFFFFFFFFF
        high_key.fmr_length = 0
        high_key_bytes = ctypes.string_at(ctypes.addressof(high_key), rec_size)
        while len(rows) < max_records:
            count = min(batch_size, max_records - len(rows))
            buf = bytearray(head_size + count * rec_size)
            head = FsMapHead.from_buffer(buf)
            head.fmh_count = count
            ctypes.memmove(ctypes.addressof(head.fmh_keys[0]), low_key_bytes, rec_size)
            ctypes.memmove(ctypes.addressof(head.fmh_keys[1]), high_key_bytes, rec_size)
            fcntl.ioctl(fd, FS_IOC_GETFSMAP, buf, True)
            entries = min(int(head.fmh_entries), count)
            if entries <= 0:
                break
            last_raw = None
            saw_last = False
            for index in range(entries):
                rec = FsMap.from_buffer(buf, head_size + index * rec_size)
                row = {
                    "device": int(rec.fmr_device),
                    "physical_start": int(rec.fmr_physical),
                    "physical_end": int(rec.fmr_physical + rec.fmr_length - 1) if rec.fmr_length else int(rec.fmr_physical),
                    "length": int(rec.fmr_length),
                    "owner": _fsmap_owner(rec.fmr_owner, rec.fmr_flags, fstype),
                    "owner_raw": int(rec.fmr_owner),
                    "logical_offset": int(rec.fmr_offset),
                    "flags": _fsmap_flags(rec.fmr_flags),
                    "flags_raw": int(rec.fmr_flags),
                }
                rows.append(row)
                last_raw = bytes(memoryview(buf)[head_size + index * rec_size: head_size + (index + 1) * rec_size])
                if int(rec.fmr_flags) & FMR_OF_LAST:
                    saw_last = True
                    break
            if saw_last or entries < count or last_raw is None:
                break
            low_key_bytes = last_raw
        if len(rows) >= max_records:
            status["truncated"] = True
        status["device_values_are_dev_t"] = bool(int(head.fmh_oflags) & FMH_OF_DEV_T) if 'head' in locals() else False
    except OSError as exc:
        if exc.errno in {errno.ENOTTY, errno.EOPNOTSUPP}:
            status["error"] = (
                f"FS_IOC_GETFSMAP is not supported for {fstype} on this kernel/filesystem."
            )
        elif exc.errno in {errno.EACCES, errno.EPERM}:
            status["error"] = "Permission denied by the kernel during physical-map acquisition."
        else:
            status["error"] = f"FS_IOC_GETFSMAP request failed: {exc}"
    finally:
        os.close(fd)
    return rows, status


# ---------------------------------------------------------------------------
# Unified selected-mount API
# ---------------------------------------------------------------------------

SUPPORTED_DEEP = {"ext4", "xfs", "btrfs"}


def deep_provider_name(record):
    fstype = str(record.get("fstype", "")).lower()
    if fstype == "ext4":
        return "ext4"
    if fstype == "xfs":
        return "XFS"
    if fstype == "btrfs":
        return "Btrfs"
    return "Unavailable"


def inspect_filesystem(record):
    fstype = str(record.get("fstype", "")).lower()
    if fstype == "ext4":
        return inspect_ext4(record)
    if fstype == "xfs":
        return inspect_xfs(record)
    if fstype == "btrfs":
        return inspect_btrfs(record)
    return {
        "provider": "Unavailable",
        "summary": {},
        "allocation_columns": [],
        "allocation": [],
        "source_status": {"provider": f"No deep provider for filesystem type {fstype or 'unknown'}"},
    }
