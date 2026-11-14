#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LinSpectacles - Linux Inspection Suite
# Copyright (C) 2026 brunonlinespace
# GPL-3.0-or-later

APPLET_ID = "linspectacles-filesystem-details"
APPLET_NAME = "Filesystem Details"
APPLET_VERSION = "0.0.8"
APPLET_AUTHOR = "brunonlinespace"
APPLET_EDITOR = "brunonlinespace"
APPLET_ORGANIZATION_ID = "linspectacles"
APPLET_ORGANIZATION_URL = "https://github.com/linspectacles/"
APPLET_REPOSITORY = "https://github.com/linspectacles/filesystem-details"

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, QSettings
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPixmap, QShortcut, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .filesystem_details import deep_provider_name
from .filesystem_dialog import FilesystemDetailsView
from .mountinfo import read_mountinfo


def _sources_groups():
    """Informational source/provenance text; never starts an inspection."""
    return [
        ("Filesystem selection", [
            "/proc/self/mountinfo lists mounts in the current process mount namespace.",
            "The initial Supported filter uses filesystem type only (ext4, XFS, Btrfs). It does not claim that inspection data is readable, and it does not scan directory contents.",
            "All Mounted Filesystems exposes the full selector, including types without a deep structural provider.",
        ]),
        ("ext4", [
            "/proc/fs/ext4/<device>/mb_groups", 
            "Selected read-only fields from /sys/fs/ext4/<device>/.",
        ]),
        ("XFS", [
            "XFS_IOC_FSGEOMETRY; XFS_IOC_AG_GEOMETRY.",
        ]),
        ("Btrfs", [
            "BTRFS_IOC_FS_INFO; BTRFS_IOC_DEV_INFO; BTRFS_IOC_SPACE_INFO.",
        ]),
        ("Physical map", [
            "FS_IOC_GETFSMAP is requested only through the explicit Map… action; refreshing the filesystem does not collect it.",
            "Owner identifiers are kernel/API values. No pathnames are inferred and no file tree is walked.",
        ]),
        ("Inspection boundary", [
            "Read-only. No raw /dev/* parsing, block-device topology inspection, recursive path scans, filesystem repair/check/scrub/balance/resize/defragment/trim, mount mutation, or administrative CLI parsing.",
        ]),
    ]


def _populate_sources(canvas):
    heading = QTextCharFormat()
    heading.setForeground(QColor("#9cdcfe"))
    heading.setFontWeight(600)
    body = QTextCharFormat()
    body.setForeground(QColor("#dcdcdc"))
    canvas.clear()
    cursor = canvas.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    for title, lines in _sources_groups():
        if cursor.position():
            cursor.insertText("\n", body)
        cursor.insertText(title + "\n", heading)
        for line in lines:
            cursor.insertText("  " + line + "\n", body)
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    canvas.setTextCursor(cursor)
    canvas.verticalScrollBar().setValue(0)


class FilesystemDetailsOptionsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("Options — Filesystem Details")
        self.resize(980, 720)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        appearance = QWidget()
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.setContentsMargins(12, 12, 12, 12)
        appearance_layout.setSpacing(10)
        appearance_title = QLabel("Metadata display")
        appearance_font = appearance_title.font()
        appearance_font.setBold(True)
        appearance_title.setFont(appearance_font)
        appearance_layout.addWidget(appearance_title)
        appearance_note = QLabel(
            "Choose how the Allocation and Physical Map inventories and Metadata Details panes "
            "are arranged. The same setting is used by both views."
        )
        appearance_note.setWordWrap(True)
        appearance_layout.addWidget(appearance_note)
        orientation_row = QHBoxLayout()
        orientation_row.addWidget(QLabel("Record details layout:"))
        orientation = QComboBox()
        orientation.addItems(["Horizontal", "Vertical"])
        orientation.setCurrentText("Vertical" if owner.details_orientation == "vertical" else "Horizontal")
        orientation.currentTextChanged.connect(lambda value: owner.set_details_orientation(value.lower()))
        orientation_row.addWidget(orientation)
        orientation_row.addStretch(1)
        appearance_layout.addLayout(orientation_row)
        show_details = QCheckBox("Show Metadata Details panel (F3)")
        show_details.setChecked(owner.details_visible)
        show_details.toggled.connect(owner.set_details_visible)
        appearance_layout.addWidget(show_details)
        shortcut_note = QLabel(
            "Shortcuts: F3 hides/restores Metadata Details; "
            "Shift+F5 refreshes the selected filesystem; "
            "Ctrl+L toggles Horizontal/Vertical layout; Ctrl+/ opens Options."
        )
        shortcut_note.setWordWrap(True)
        appearance_layout.addWidget(shortcut_note)
        appearance_layout.addStretch(1)
        tabs.addTab(appearance, "Appearance")

        sources_page = QWidget()
        sources_layout = QVBoxLayout(sources_page)
        sources_layout.setContentsMargins(12, 12, 12, 12)
        sources_layout.setSpacing(10)
        sources_heading = QLabel("Data Sources")
        sources_font = sources_heading.font()
        sources_font.setBold(True)
        sources_font.setPointSize(max(sources_font.pointSize(), 11))
        sources_heading.setFont(sources_font)
        sources_layout.addWidget(sources_heading)
        sources_note = QLabel("Local Linux interfaces used for mounted-filesystem structural inspection. Physical mapping requires an explicit request.")
        sources_note.setWordWrap(True)
        sources_layout.addWidget(sources_note)
        sources = QTextEdit()
        sources.setReadOnly(True)
        sources.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        owner.details_view.style_sources(sources)
        _populate_sources(sources)
        sources_layout.addWidget(sources, 1)
        tabs.addTab(sources_page, "Sources")

        export_page = QWidget()
        export_layout = QVBoxLayout(export_page)
        export_layout.setContentsMargins(12, 12, 12, 12)
        export_layout.setSpacing(10)
        export_heading = QLabel("Export")
        export_font = export_heading.font()
        export_font.setBold(True)
        export_heading.setFont(export_font)
        export_layout.addWidget(export_heading)
        export_note = QLabel(
            "Choose which filesystem views to include in one export. Only already-acquired "
            "data is used: selecting Physical Map does not run Map… automatically. "
            "Uncollected or unavailable data is identified explicitly."
        )
        export_note.setWordWrap(True)
        export_layout.addWidget(export_note)
        self.export_view_checks = {}
        for key, label in owner.export_view_specs():
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            self.export_view_checks[key] = checkbox
            export_layout.addWidget(checkbox)
        export_layout.addStretch(1)
        export_row = QHBoxLayout()
        export_row.addStretch(1)
        export_button = QPushButton("Export Selected Views…")
        export_button.clicked.connect(self._export_selected)
        export_row.addWidget(export_button)
        export_layout.addLayout(export_row)
        tabs.addTab(export_page, "Export")

        about_page = QWidget()
        about_layout = QVBoxLayout(about_page)
        about_layout.setContentsMargins(24, 20, 24, 18)
        about_layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(112, 112)
        icon_path = Path(__file__).resolve().parent / "icon.png"
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(
                        112, 112,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        about_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel("<h2 style='margin:0'>Filesystem Details</h2>")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(name)

        version = QLabel(f"Version {APPLET_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(version)

        slogan = QLabel("<b>Expose. Explore. Explain.</b>")
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(slogan)

        description = QLabel(
            "A read-only LinSpectacles applet for deep structural inspection of "
            "selected mounted ext4, XFS, and Btrfs filesystems."
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(description)

        details = QLabel(
            "<b>Build:</b> Standalone LinSpectacles applet<br>"
            "<b>Organisation ID:</b> "
            f"<a href='{APPLET_ORGANIZATION_URL}'>{APPLET_ORGANIZATION_ID}</a><br>"
            f"<b>Applet ID:</b> {APPLET_ID}"
        )
        details.setWordWrap(True)
        details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details.setOpenExternalLinks(True)
        details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(details)

        copyright_label = QLabel(
            "Copyright © 2026 "
            "<a href='https://github.com/brunonlinespace'>brunonlinespace</a>"
        )
        copyright_label.setOpenExternalLinks(True)
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(copyright_label)

        license_label = QLabel("Licensed under GNU GPLv3 or later.")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(license_label)

        readme_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent.parent / "README.md")
        ).toString()
        license_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent.parent / "LICENSE")
        ).toString()
        links = QLabel(
            f"<a href='{readme_url}'>README</a> "
            "&nbsp;·&nbsp; "
            f"<a href='{license_url}'>License</a> "
            "&nbsp;·&nbsp; "
            f"<a href='{APPLET_REPOSITORY}'>Repository</a>"
        )
        links.setOpenExternalLinks(True)
        links.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(links)
        about_layout.addStretch(1)
        tabs.addTab(about_page, "About")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _export_selected(self):
        selected = [
            key for key, checkbox in self.export_view_checks.items()
            if checkbox.isChecked()
        ]
        self.owner.export_selected_views(selected, parent=self)


class FilesystemDetailsApplet(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []
        self.visible_records = []
        self._metadata_font = None
        self.settings = QSettings("brunonlinespace", "linspectacles-filesystem-details")
        self.details_orientation = str(self.settings.value("details_orientation", "horizontal")).lower()
        if self.details_orientation not in {"horizontal", "vertical"}:
            self.details_orientation = "horizontal"
        self.details_visible = str(self.settings.value("details_visible", "true")).lower() not in {"false", "0", "no"}
        self._build_ui()
        self._install_shortcuts()
        self.refresh_filesystems()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("Filesystem Details")
        heading_font = heading.font()
        heading_font.setBold(True)
        heading_font.setPointSize(max(heading_font.pointSize(), 11))
        heading.setFont(heading_font)
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.summary_btn = QPushButton("Summary…")
        self.summary_btn.clicked.connect(self.show_summary)
        heading_row.addWidget(self.summary_btn)
        self.refresh_list_btn = QPushButton("Refresh List")
        self.refresh_list_btn.clicked.connect(self.refresh_filesystems)
        heading_row.addWidget(self.refresh_list_btn)
        self.options_btn = QPushButton("Options…")
        self.options_btn.clicked.connect(self.show_options)
        heading_row.addWidget(self.options_btn)
        root.addLayout(heading_row)

        selector_row = QHBoxLayout()
        selector_heading = QLabel("Filesystem:")
        bold = selector_heading.font()
        bold.setBold(True)
        selector_heading.setFont(bold)
        selector_row.addWidget(selector_heading)
        self.filesystem_combo = QComboBox()
        self.filesystem_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.filesystem_combo.setMinimumContentsLength(25)
        self.filesystem_combo.currentIndexChanged.connect(self._selection_changed)
        selector_row.addWidget(self.filesystem_combo, 1)
        selector_row.addWidget(QLabel("Show:"))
        self.mount_filter = QComboBox()
        self.mount_filter.addItems(["Supported (ext4, XFS, Btrfs)", "All Mounted Filesystems"])
        saved_filter = str(self.settings.value("mount_filter", "supported"))
        self.mount_filter.setCurrentIndex(1 if saved_filter == "all" else 0)
        self.mount_filter.currentIndexChanged.connect(self._filter_changed)
        selector_row.addWidget(self.mount_filter)
        root.addLayout(selector_row)

        self.details_view = FilesystemDetailsView(self)
        root.addWidget(self.details_view, 1)

    def _install_shortcuts(self):
        for sequence, callback in (
            ("Shift+F5", self.refresh_filesystems),
            ("Ctrl+/", self.show_options),
            ("F3", self.toggle_details),
            ("Ctrl+L", self.toggle_orientation),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    def _filter_changed(self, _index):
        self.settings.setValue("mount_filter", "all" if self.mount_filter.currentIndex() == 1 else "supported")
        self._fill_selector()

    def refresh_filesystems(self):
        try:
            self.records = read_mountinfo()
        except Exception as exc:
            self.records = []
            self._fill_selector()
            QMessageBox.warning(self, "Filesystem Details", f"Unable to enumerate mounted filesystems:\n{exc}")
            return
        self._fill_selector()

    def _fill_selector(self):
        previous_id = self.filesystem_combo.currentData()
        supported_only = self.mount_filter.currentIndex() == 0
        self.visible_records = [
            record for record in self.records
            if not supported_only or deep_provider_name(record) != "Unavailable"
        ]
        self.filesystem_combo.blockSignals(True)
        self.filesystem_combo.clear()
        selected_index = -1
        for index, record in enumerate(self.visible_records):
            mount_id = str(record.get("mount_id", ""))
            mount_point = str(record.get("mount_point", ""))
            fstype = str(record.get("fstype", ""))
            source = str(record.get("source", ""))
            self.filesystem_combo.addItem(f"{mount_point} — {fstype} — {source}", mount_id)
            if previous_id is not None and str(previous_id) == mount_id:
                selected_index = index
        if selected_index < 0 and self.visible_records:
            selected_index = 0
        self.filesystem_combo.setCurrentIndex(selected_index)
        self.filesystem_combo.blockSignals(False)
        self._selection_changed(selected_index)

    def _selection_changed(self, index):
        if 0 <= index < len(self.visible_records):
            record = self.visible_records[index]
            self.details_view.set_record(record)
            self.summary_btn.setEnabled(True)
        else:
            self.details_view.set_record(None)
            self.summary_btn.setEnabled(False)

    def show_summary(self):
        self.details_view.show_summary()

    def toggle_details(self):
        self.set_details_visible(not self.details_visible)

    def set_details_visible(self, visible):
        self.details_visible = bool(visible)
        self.details_view.set_details_visible(self.details_visible)
        self.settings.setValue("details_visible", self.details_visible)

    def toggle_orientation(self):
        self.set_details_orientation("vertical" if self.details_orientation == "horizontal" else "horizontal")

    def set_details_orientation(self, orientation):
        if orientation not in {"horizontal", "vertical"}:
            return
        self.details_view.set_details_orientation(orientation)
        self.details_orientation = orientation
        self.settings.setValue("details_orientation", orientation)

    def show_options(self):
        FilesystemDetailsOptionsDialog(self).exec()

    def apply_host_settings(self, settings=None, column_visibility_callback=None):
        settings = settings or {}
        self.details_view.apply_host_font(settings.get("metadata_font", ""))

    def set_theme_colors(self, text_bg, text_fg, key_fg, value_fg, status_bg, status_fg):
        self.details_view.set_theme_colors(
            text_bg, text_fg, key_fg, value_fg, status_bg, status_fg
        )

    def get_export_records(self):
        return self.details_view.get_export_records()

    def export_view_specs(self):
        return [
            ("summary", "Filesystem Summary"),
            ("allocation", "Allocation"),
            ("map", "Physical Map"),
        ]

    def export_selected_views(self, selected, parent=None):
        self.details_view.export_selected_views(selected, parent=parent)

    def export_current_data(self):
        # Suite API: export lives in Options → Export, not on the main applet surface.
        self.show_options()


def create_applet(parent=None):
    return FilesystemDetailsApplet(parent=parent)


def run_standalone():
    import sys
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from ._support import STANDALONE_STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName(APPLET_NAME)
    app.setOrganizationName(APPLET_AUTHOR)
    icon_path = Path(__file__).resolve().parent / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(STANDALONE_STYLESHEET)
    window = QMainWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.setWindowTitle(f"{APPLET_NAME} {APPLET_VERSION} — LinSpectacles Applet")
    window.resize(1200, 780)
    window.setCentralWidget(create_applet())
    window.show()
    return app.exec()
