# Filesystem Details

**Expose. Explore. Explain.**

Filesystem Details is a read-only LinSpectacles applet for deep structural inspection of a selected mounted filesystem.

Current release: **0.0.8**

Repository: <https://github.com/linspectacles/filesystem-details>

## Scope

The applet selects a mounted filesystem from `/proc/self/mountinfo` and then performs filesystem-specific deep structural inspection.

It does **not** provide a searchable mount inventory, mount-category filters, mount Metadata Details, mount relationships, or a mount-capacity inventory.

Supported deep providers are ext4, XFS and Btrfs. The selector defaults to **Supported (ext4, XFS, Btrfs)**, based on filesystem type reported by mountinfo, so pseudo-filesystems do not crowd the initial list. **All Mounted Filesystems** remains available to select unsupported types, which report that no deep structural provider is available. This filter does not read directory contents or guarantee that the supported deep provider will return data.

## Details surfaces

- **Summary…** — top-right action opening a read-only filesystem-native structural summary and source-status dialog, styled with the same blue keys, light values and dark canvas as the SELinux Inspector status dialog and Options → Sources.
- **Allocation** — main tab with an inventory and a matching Metadata Details pane for ext4 allocator groups, XFS allocation groups, or Btrfs space classes/profiles as reported by the selected provider.
- **Physical Map** — main tab with inventory and Metadata Details. The **Map…** button appears at the far right of the Search row, without an Actions label. Explicit `FS_IOC_GETFSMAP` acquisition only; never collected automatically by normal Refresh.

The main UI follows SELinux Inspector's margins and padding, heading, top-right actions, search/filter-to-selection behaviour, Metadata Details panel and horizontal/vertical splitter control. There is no overall bottom status bar. Each tab has a neutral, SELinux-style italic status label with 4 px contents margins and no additional stylesheet padding or forced colours; acquisition and record selection update its message. Inventory Metadata Details uses the host-selected metadata font through SELinux-compatible cursor-based rendering, with teal keys and orange values. Summary and Options → Sources use the distinct dark canvas (`#151719`), blue headings/keys (`#9cdcfe`), light values (`#dcdcdc`) and subtle border (`#333333`). Export appears only in Options → Export, with individual checkboxes for Summary, Allocation and Physical Map and a consolidated export of selected, already-acquired data. No physical map is collected by exporting.

## Data sources

- Target selection: `/proc/self/mountinfo`.
- ext4: `/proc/fs/ext4/<device>/mb_groups` and selected `/sys/fs/ext4/<device>/` fields.
- XFS: `XFS_IOC_FSGEOMETRY` and `XFS_IOC_AG_GEOMETRY`.
- Btrfs: `BTRFS_IOC_FS_INFO`, `BTRFS_IOC_DEV_INFO` and `BTRFS_IOC_SPACE_INFO`.
- Physical map: `FS_IOC_GETFSMAP` only when explicitly requested.

## Read-only boundary

Filesystem Details does not mount, unmount or remount filesystems; parse raw `/dev/*`; inspect block-device topology; recursively walk file trees; or perform repair, check, scrub, balance, resize, defragment, trim or other mutating filesystem operations.

## Keyboard shortcuts

| Command | Shortcut |
| --- | --- |
| Refresh filesystem selector and selected filesystem | `Shift+F5` |
| Show/hide Metadata Details | `F3` |
| Toggle Horizontal/Vertical Metadata Details | `Ctrl+L` |
| Options | `Ctrl+/` |

## Running from source

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install PyQt6
python3 linspectacles_filesystem_details/standalone.py
```

## Source layout

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

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).

## Links

- LinSpectacles organisation: <https://github.com/linspectacles/>
- Repository: <https://github.com/linspectacles/filesystem-details>
- Issues: <https://github.com/linspectacles/filesystem-details/issues>
