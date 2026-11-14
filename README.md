# Filesystem Details

**Expose. Explore. Explain.**

Filesystem Details is a read-only LinSpectacles applet for deep structural inspection of a selected mounted filesystem.

Current release: **0.0.8**

Repository: <https://github.com/linspectacles/filesystem-details>

<p align="center">
  <a href="https://github.com/brunonlinespace/brunonlinespace/blob/main/linspectacles/filesystem-details.png">
    <img
      src="https://raw.githubusercontent.com/brunonlinespace/brunonlinespace/main/linspectacles/filesystem-details.png"
      alt="Filesystem Details screenshot"
      width="900"
    >
  </a>
</p>

## What Filesystem Details is

Filesystem Details is a specialist structural filesystem inspector.

It selects a mounted filesystem from `/proc/self/mountinfo` and then uses filesystem-native Linux interfaces to inspect structural information for supported **ext4**, **XFS**, and **Btrfs** filesystems.

Its purpose is deliberately narrower than a general mount browser. Filesystem Details does **not** provide the main searchable mount inventory, capacity overview, mount-category filtering, or mount relationships supplied by **Mounted Filesystems**. Instead, it begins with one selected mount and goes deeper into filesystem-specific structure.

The applet is read-only. It does not mount, unmount, remount, repair, scrub, balance, resize, defragment, trim, or otherwise modify the selected filesystem.

## Highlights

- Selects the inspection target from the current process mount namespace via `/proc/self/mountinfo`.
- Defaults to **Supported (ext4, XFS, Btrfs)** so pseudo-filesystems and unsupported filesystem types do not crowd the initial selector.
- **All Mounted Filesystems** remains available so unsupported mounts can still be selected and identified honestly.
- Dedicated filesystem-native providers for **ext4**, **XFS**, and **Btrfs**.
- **Summary...** dialog for filesystem-native structural summary and source status.
- **Allocation** inventory with matching Metadata Details.
- Explicit **Physical Map** acquisition through `FS_IOC_GETFSMAP`.
- Physical mapping is never acquired automatically by Refresh or Export.
- Search and selection remain synchronized with Metadata Details.
- Horizontal / Vertical Metadata Details layout.
- Consolidated export for selected, already-acquired **Summary**, **Allocation**, and **Physical Map** data.
- Unsupported filesystem types remain selectable but report that no deep structural provider is available rather than falling back to generic invented data.

## Filesystem selection

The target selector is built from:

```text
/proc/self/mountinfo
```

The default filter is:

```text
Supported (ext4, XFS, Btrfs)
```

This filter is based only on the filesystem type reported by mountinfo.

It does not read directory contents, probe raw block devices, guarantee deeper provider data will be readable, or treat an unsupported filesystem as erroneous.

The alternative:

```text
All Mounted Filesystems
```

shows the full mount set visible in the current process mount namespace.

Selecting an unsupported filesystem is valid. The applet reports that no deep structural provider is available for that filesystem type.

## Details surfaces

### Summary...

**Summary...** is a top-right action that opens a read-only filesystem-native structural summary and source-status dialog.

The Summary surface uses the established LinSpectacles dark information canvas with blue keys/headings and light values.

Its contents depend on the selected filesystem and on what that filesystem's provider can report.

### Allocation

The **Allocation** tab presents filesystem-native structural allocation records.

For supported providers, the inventory represents different filesystem concepts rather than forcing them into one false universal model:

- **ext4** — multiblock allocator buddy-cache groups.
- **XFS** — allocation-group geometry and reported health information.
- **Btrfs** — filesystem-native space classes / profiles.

Selecting a row updates the matching Metadata Details pane.

### Physical Map

The **Physical Map** tab provides explicit filesystem mapping data using:

```text
FS_IOC_GETFSMAP
```

Acquisition happens only when the user presses **Map...**.

The physical map is **not** collected by ordinary Refresh, selecting the tab, changing the search filter, or exporting other data.

Exporting Physical Map data uses already-acquired map records and does not silently cause a new map acquisition.

## Data sources and acquisition

### Target selection

- `/proc/self/mountinfo`
- current mount-namespace identity through `/proc/self/ns/mnt`
- `statvfs()` where filesystem capacity/limit context is needed.

### ext4

- `/proc/fs/ext4/<device>/mb_groups`
- selected read-only fields under `/sys/fs/ext4/<device>/`

Filesystem Details resolves the ext4 runtime-provider name from the selected mount source. It does not use `/sys/class/block` or `/sys/dev/block` as a substitute topology source.

### XFS

- `XFS_IOC_FSGEOMETRY`
- `XFS_IOC_AG_GEOMETRY`

### Btrfs

- `BTRFS_IOC_FS_INFO`
- `BTRFS_IOC_DEV_INFO`
- `BTRFS_IOC_SPACE_INFO`

### Physical map

- `FS_IOC_GETFSMAP`

This interface is used only after explicit **Map...** acquisition.

The applet reports information available from its documented Linux sources. Data that is unavailable, restricted, or not reported by those sources remains explicitly unavailable rather than being inferred.

## Interface

The main window keeps filesystem selection separate from the deeper filesystem-specific views.

The primary work area provides:

- **Allocation**
- **Physical Map**

A **Search** field filters the active inventory without changing acquisition.

Metadata Details follows the current selected inventory record and can be shown/hidden or arranged horizontally/vertically.

Each main tab uses its own neutral status surface for acquisition and selection information. There is no separate overall bottom status bar.

The **Options...** dialog provides:

- **Appearance**
- **Sources**
- **Export**
- **About**

Export allows the user to choose from already-acquired:

- Summary
- Allocation
- Physical Map

No hidden Physical Map scan is triggered merely because Physical Map is selected for export.

## Read-only boundary

Filesystem Details does not:

- mount, unmount, or remount filesystems.
- parse raw `/dev/*` filesystem structures.
- inspect general block-device topology.
- recursively walk file trees.
- repair filesystems.
- run mutating filesystem checks.
- scrub or balance Btrfs.
- resize filesystems.
- defragment filesystems.
- issue trim/discard operations.
- write filesystem metadata.
- mutate allocator state.
- acquire a Physical Map unless explicitly requested.

## Useful keyboard shortcuts

| Command | Shortcut |
| --- | --- |
| Refresh filesystem selector and selected filesystem | `Shift+F5` |
| Show / hide Metadata Details | `F3` |
| Toggle Horizontal / Vertical Metadata Details | `Ctrl+L` |
| Options | `Ctrl+/` |

## Running from source

The supplied source is directly runnable on Linux. The Python-side requirements are Python 3 and PyQt6.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install PyQt6
python3 linspectacles_filesystem_details/standalone.py
```

Filesystem-specific information comes from the Linux interfaces described under **Data sources and acquisition**; no separate userspace filesystem-analysis suite is required for the implemented 0.0.8 providers.

No RPM installation instructions are included in this README.

## LinSpectacles Hub

This applet can run independently, but it can also be installed and used inside **[LinSpectacles Hub](https://github.com/linspectacles/linspectacles-hub)**.

LinSpectacles Hub is the optional workbench for the LinSpectacles applet family. It provides shared applet discovery, navigation and management while each inspector remains independently runnable.

To install a portable or user applet through the Hub, open **Configuration... → Applets** and add the applet ZIP. Once discovered, the applet can be enabled and opened from the Hub navigation.

System-installed applets are discovered by the Hub from its system applet store and remain managed by the system package manager.

## Source layout and LinSpectacles integration

```text
linspectacles_filesystem_details/
├── __init__.py
├── applet.json
├── standalone.py
├── README.md
├── LICENSE
└── filesystem_details/
    ├── __init__.py
    ├── _support.py
    ├── applet.py
    ├── filesystem_details.py
    ├── filesystem_dialog.py
    ├── mountinfo.py
    └── icon.png
```

`applet.json` defines the applet's LinSpectacles identity and integration metadata. `standalone.py` provides direct standalone launching, while the applet entrypoint allows the same inspector to run inside LinSpectacles Hub.

## Configuration

Filesystem Details persists implemented presentation state using its existing settings model.

Persisted UI state does not alter the selected filesystem or grant additional filesystem access.

## Scope

Filesystem Details is intentionally a **deep selected-filesystem inspector**, not the general LinSpectacles mount inventory.

**Mounted Filesystems** remains the specialist applet for mount inventory, mount relationships, capacity/state overview, and mounted-filesystem browsing.

**Block Devices** remains the specialist applet for block-device inventory and device-level information.

Filesystem Details answers:

> **What structural information does this selected mounted filesystem expose through its filesystem-native interfaces?**

It does not replace broader mount or block-device inspection.

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).

## Links

- LinSpectacles organisation: <https://github.com/linspectacles/>
- LinSpectacles Hub: <https://github.com/linspectacles/linspectacles-hub>
- Repository: <https://github.com/linspectacles/filesystem-details>
- Issues: <https://github.com/linspectacles/filesystem-details/issues>

<p align="center">
  <a href="https://github.com/linspectacles/filesystem-details">
    <img
      src="filesystem_details/icon.png"
      alt="Filesystem Details"
      width="256"
    >
  </a>
</p>
