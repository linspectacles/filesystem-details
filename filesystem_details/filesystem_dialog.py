#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qt structural-details view for one selected mounted filesystem."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QFrame, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

try:
    from ._support import MetadataHighlighter, NumericTableWidgetItem, export_records_dialog, metadata_font_qss, apply_metadata_font, default_metadata_font
    from .filesystem_details import filesystem_map, inspect_filesystem
    from .mountinfo import format_bytes
except ImportError:
    from _support import MetadataHighlighter, NumericTableWidgetItem, export_records_dialog, metadata_font_qss, apply_metadata_font, default_metadata_font
    from filesystem_details import filesystem_map, inspect_filesystem
    from mountinfo import format_bytes


def _display_value(key, value):
    if value is None:
        return "Unavailable"
    if key in {"total_bytes", "used_bytes", "free_bytes"} and isinstance(value, int):
        return format_bytes(value)
    if key in {"length", "physical_start", "physical_end", "logical_offset"} and isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return str(value)


class FilesystemDetailsView(QWidget):
    """Two Path-style inventory/metadata tabs plus a demand-driven summary."""

    def __init__(self, owner, record=None):
        super().__init__(owner)
        self.owner = owner
        self.record = dict(record or {})
        self.deep = None
        self.map_rows = []
        self.map_status = None
        self._summary_text = ""
        self._allocation_columns = []
        self._text_bg = "#1e1e1e"
        self._text_fg = "#dcdcdc"
        self._key_color = "#4ec9b0"
        self._value_color = "#ce9178"
        self._serialized_metadata_font = ""
        self._metadata_font = default_metadata_font()
        self.owner._metadata_font = self._metadata_font
        self._allocation_status_base = "Ready - Select an allocation unit to inspect properties."
        self._map_status_base = "Physical filesystem map has not been collected."
        self._build_ui()
        self.set_details_orientation(self.owner.details_orientation, initial=True)
        self.set_details_visible(self.owner.details_visible)
        if self.record:
            self.refresh_details()
        else:
            self.clear_details()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        root.addWidget(self.tabs, 1)

        allocation_page = QWidget()
        allocation_layout = QVBoxLayout(allocation_page)
        allocation_layout.setContentsMargins(12, 12, 12, 12)
        allocation_layout.setSpacing(10)
        allocation_search_row = QHBoxLayout()
        allocation_search_label = QLabel("Search:")
        allocation_search_label.setStyleSheet("font-weight: 600;")
        allocation_search_row.addWidget(allocation_search_label)
        self.allocation_search = QLineEdit()
        self.allocation_search.setPlaceholderText("Search allocation units...")
        self.allocation_search.setMaximumWidth(280)
        self.allocation_search.textChanged.connect(lambda _text: self._filter_table("allocation"))
        allocation_search_row.addWidget(self.allocation_search)
        self.allocation_count = QLabel("")
        cf = self.allocation_count.font()
        cf.setItalic(True)
        self.allocation_count.setFont(cf)
        allocation_search_row.addWidget(self.allocation_count)
        allocation_search_row.addStretch(1)
        allocation_layout.addLayout(allocation_search_row)

        self.allocation_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.allocation_table = QTableWidget(0, 0)
        self._configure_table(self.allocation_table)
        self.allocation_table.itemSelectionChanged.connect(self._allocation_selected)
        self.allocation_splitter.addWidget(self.allocation_table)
        self.allocation_panel, self.allocation_details = self._make_details_panel()
        self.allocation_splitter.addWidget(self.allocation_panel)
        self.allocation_splitter.splitterMoved.connect(lambda *_: self._save_splitter("allocation"))
        allocation_layout.addWidget(self.allocation_splitter, 1)
        self.allocation_note = self._make_status_label()
        allocation_layout.addWidget(self.allocation_note)
        self.tabs.addTab(allocation_page, "Allocation")

        map_page = QWidget()
        map_layout = QVBoxLayout(map_page)
        map_layout.setContentsMargins(12, 12, 12, 12)
        map_layout.setSpacing(10)
        map_search_row = QHBoxLayout()
        map_search_label = QLabel("Search:")
        map_search_label.setStyleSheet("font-weight: 600;")
        map_search_row.addWidget(map_search_label)
        self.map_search = QLineEdit()
        self.map_search.setPlaceholderText("Search collected physical mappings...")
        self.map_search.setMaximumWidth(280)
        self.map_search.textChanged.connect(lambda _text: self._filter_table("map"))
        map_search_row.addWidget(self.map_search)
        self.map_count = QLabel("")
        mf = self.map_count.font()
        mf.setItalic(True)
        self.map_count.setFont(mf)
        map_search_row.addWidget(self.map_count)
        map_search_row.addStretch(1)
        self.map_btn = QPushButton("Map…")
        self.map_btn.clicked.connect(self.acquire_map)
        map_search_row.addWidget(self.map_btn)
        map_layout.addLayout(map_search_row)
        self.map_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.map_table = QTableWidget(0, 6)
        self.map_table.setHorizontalHeaderLabels([
            "Device", "Physical Start", "Length", "Owner", "Logical Offset", "Flags"
        ])
        self._configure_table(self.map_table)
        self.map_table.itemSelectionChanged.connect(self._map_selected)
        self.map_splitter.addWidget(self.map_table)
        self.map_panel, self.map_details = self._make_details_panel()
        self.map_splitter.addWidget(self.map_panel)
        self.map_splitter.splitterMoved.connect(lambda *_: self._save_splitter("map"))
        map_layout.addWidget(self.map_splitter, 1)
        self.map_note = self._make_status_label()
        map_layout.addWidget(self.map_note)
        self._update_tab_status("allocation")
        self._update_tab_status("map")
        self.tabs.addTab(map_page, "Physical Map")

    def _make_status_label(self):
        """SELinux-style, tab-local status surface; no overall applet status bar."""
        label = QLabel("")
        status_font = label.font()
        status_font.setItalic(True)
        label.setFont(status_font)
        label.setFrameShape(QFrame.Shape.NoFrame)
        label.setContentsMargins(4, 4, 4, 4)
        # SELinux BaseInspectorTab's ordinary initial status geometry uses
        # only setContentsMargins(4, 4, 4, 4).  Do not layer a stylesheet
        # padding on top: that changes the tab's bottom-row height and inset.
        return label

    def _update_tab_status(self, which):
        if which == "allocation":
            label = self.allocation_note
            base = self._allocation_status_base
            table = self.allocation_table
        else:
            label = self.map_note
            base = self._map_status_base
            table = self.map_table
        row = table.currentRow()
        if (row >= 0 and not table.isRowHidden(row)
                and table.selectionModel() is not None
                and table.selectionModel().hasSelection()):
            item = table.item(row, 0)
            if item is not None:
                base = f"{base}  Selected: {item.text()}."
        label.setText(base)

    def _set_tab_status(self, which, text):
        if which == "allocation":
            self._allocation_status_base = str(text)
        else:
            self._map_status_base = str(text)
        self._update_tab_status(which)

    def _make_details_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        label = QLabel("Metadata Details")
        font = label.font()
        font.setBold(True)
        font.setPointSize(max(font.pointSize(), 11))
        label.setFont(font)
        layout.addWidget(label)
        info = QTextEdit()
        info.setReadOnly(True)
        info.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._apply_metadata_font(info)
        info.metadata_highlighter = MetadataHighlighter(info.document())
        layout.addWidget(info, 1)
        return panel, info

    @staticmethod
    def _replace_info(widget, text):
        """SELinux's clear/append cursor pattern, preserving the host document font."""
        widget.clear()
        cursor = widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(str(text))
        widget.setTextCursor(cursor)
        widget.moveCursor(QTextCursor.MoveOperation.Start)

    def _apply_metadata_font(self, widget):
        font = apply_metadata_font(widget, self._serialized_metadata_font)
        self._metadata_font = font
        widget.setStyleSheet(
            "QTextEdit { " + metadata_font_qss(font) +
            f" background-color: {self._text_bg}; color: {self._text_fg}; border: 1px solid #666; }}"
        )

    def style_sources(self, widget):
        font = apply_metadata_font(widget, self._serialized_metadata_font)
        widget.setStyleSheet(
            "QTextEdit { " + metadata_font_qss(font) +
            " background-color: #151719; color: #dcdcdc; border: 1px solid #333333; }"
        )

    def apply_host_font(self, serialized=""):
        self._serialized_metadata_font = serialized
        for widget in (self.allocation_details, self.map_details):
            self._apply_metadata_font(widget)
        self.owner._metadata_font = self._metadata_font

    def set_theme_colors(self, text_bg, text_fg, key_fg, value_fg, status_bg, status_fg):
        self._text_bg = str(text_bg)
        self._text_fg = str(text_fg)
        self._key_color = str(key_fg)
        self._value_color = str(value_fg)
        for widget in (self.allocation_details, self.map_details):
            self._apply_metadata_font(widget)
            widget.metadata_highlighter.set_colors(
                QColor(self._key_color), QColor(self._value_color), QColor(self._text_fg)
            )

    def set_details_visible(self, visible):
        self.allocation_panel.setVisible(bool(visible))
        self.map_panel.setVisible(bool(visible))

    def set_details_orientation(self, orientation, initial=False):
        desired = Qt.Orientation.Vertical if orientation == "vertical" else Qt.Orientation.Horizontal
        for key, splitter in (("allocation", self.allocation_splitter), ("map", self.map_splitter)):
            if not initial:
                self._save_splitter(key)
            splitter.setOrientation(desired)
            panel = splitter.widget(1)
            details_layout = panel.layout() if panel is not None else None
            if details_layout is not None:
                if orientation == "vertical":
                    details_layout.setContentsMargins(0, 8, 0, 0)
                else:
                    details_layout.setContentsMargins(8, 0, 0, 0)
            sizes = self.owner.settings.value(f"{key}/splitter/{orientation}")
            default_sizes = [430, 330] if orientation == "vertical" else [480, 700]
            try:
                values = [int(v) for v in sizes] if isinstance(sizes, list) and len(sizes) == 2 else default_sizes
            except (TypeError, ValueError):
                values = default_sizes
            splitter.setSizes(values)

    def _save_splitter(self, key):
        splitter = self.allocation_splitter if key == "allocation" else self.map_splitter
        self.owner.settings.setValue(
            f"{key}/splitter/{self.owner.details_orientation}", splitter.sizes()
        )

    @staticmethod
    def _configure_table(table):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(True)

    def _filter_table(self, which):
        if which == "allocation":
            table, search, count, details = (
                self.allocation_table, self.allocation_search,
                self.allocation_count, self.allocation_details,
            )
        else:
            table, search, count, details = (
                self.map_table, self.map_search,
                self.map_count, self.map_details,
            )
        needle = search.text().strip().casefold()
        visible = []
        for row in range(table.rowCount()):
            haystack = " ".join(
                (table.item(row, col).text() if table.item(row, col) is not None else "")
                for col in range(table.columnCount())
            ).casefold()
            match = not needle or needle in haystack
            table.setRowHidden(row, not match)
            if match:
                visible.append(row)
        count.setText(f"{len(visible):,} / {table.rowCount():,} shown")
        if not visible:
            table.clearSelection()
            details.clear()
        elif table.currentRow() not in visible or not table.selectionModel().hasSelection():
            table.selectRow(visible[0])
        self._update_tab_status(which)

    def set_record(self, record):
        self.record = dict(record or {})
        if self.record:
            self.refresh_details()
        else:
            self.clear_details()

    def clear_details(self):
        self.deep = None
        self.map_rows = []
        self.map_status = None
        self._summary_text = ""
        self.allocation_table.setSortingEnabled(False)
        self.allocation_table.clear()
        self.allocation_table.setRowCount(0)
        self.allocation_table.setColumnCount(0)
        self.allocation_table.setSortingEnabled(True)
        self.allocation_details.clear()
        self._set_tab_status("allocation", "No mounted filesystem selected.")
        self.map_table.setRowCount(0)
        self.map_details.clear()
        self._set_tab_status("map", "Physical filesystem map has not been collected.")
        self.map_btn.setEnabled(False)
        self._filter_table("allocation")
        self._filter_table("map")

    def refresh_details(self):
        if not self.record:
            self.clear_details()
            return
        self.map_btn.setEnabled(True)
        self.deep = inspect_filesystem(self.record)
        self.map_rows = []
        self.map_status = None
        self.map_table.setRowCount(0)
        self.map_details.clear()
        self._set_tab_status("map", "Physical filesystem map has not been collected for this acquisition.")
        self._populate_summary()
        self._populate_allocation()
        self._filter_table("map")

    def show_summary(self):
        if not self.record or not self.deep:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Filesystem Summary — Filesystem Details")
        dialog.resize(980, 720)
        root = QVBoxLayout(dialog)
        note = QLabel(
            "Read-only structural state reported for the selected mounted filesystem. "
            "No filesystem changes are made."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        canvas = QTextEdit()
        canvas.setReadOnly(True)
        canvas.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.style_sources(canvas)
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9cdcfe"))
        key_format.setFontWeight(600)
        value_format = QTextCharFormat()
        value_format.setForeground(QColor("#dcdcdc"))
        cursor = canvas.textCursor()
        for line in self._summary_text.splitlines():
            if line.startswith("--- ") and line.endswith(" ---"):
                cursor.insertText(line + "\n", key_format)
            elif ": " in line:
                key, value = line.split(": ", 1)
                cursor.insertText(key + ": ", key_format)
                cursor.insertText(value + "\n", value_format)
            else:
                cursor.insertText(line + "\n", value_format)
        canvas.setTextCursor(cursor)
        canvas.moveCursor(QTextCursor.MoveOperation.Start)
        canvas.verticalScrollBar().setValue(0)
        page_layout.addWidget(canvas, 1)
        root.addWidget(page, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        root.addWidget(close)
        dialog.exec()

    def _populate_summary(self):
        lines = ["--- MOUNT ---"]
        for key, value in (
            ("Mount Point", self.record.get("mount_point", "")),
            ("Source", self.record.get("source", "")),
            ("Filesystem Type", self.record.get("fstype", "")),
            ("Kernel Device ID", self.record.get("major_minor", "")),
            ("Root within Filesystem", self.record.get("root", "")),
        ):
            lines.append(f"{key}: {value}")

        lines.extend(["", "--- FILESYSTEM STRUCTURE ---"])
        lines.append(f"Deep Provider: {self.deep.get('provider', 'Unavailable')}")
        summary = self.deep.get("summary", {})
        if summary:
            for key, value in summary.items():
                pretty = str(key).replace("_", " ").title() if "_" in str(key) else str(key)
                if str(key).endswith("bytes") and isinstance(value, int):
                    rendered = f"{format_bytes(value)} ({value:,} bytes)"
                else:
                    rendered = _display_value(str(key), value)
                lines.append(f"{pretty}: {rendered}")
        else:
            lines.append("Details: Deep structural provider unavailable or returned no summary fields")

        devices = self.deep.get("devices", [])
        if devices:
            lines.extend(["", "--- FILESYSTEM DEVICES — REPORTED BY FILESYSTEM ---"])
            for dev in devices:
                lines.append(
                    f"Device {dev.get('device_id')}: {dev.get('path') or 'Path not reported'} · "
                    f"{format_bytes(dev.get('bytes_used', 0))} used of {format_bytes(dev.get('total_bytes', 0))} · "
                    f"UUID {dev.get('device_uuid', '')}"
                )

        lines.extend(["", "--- SOURCE STATUS ---"])
        for source, state in self.deep.get("source_status", {}).items():
            lines.append(f"{source}: {state}")
        lines.extend([
            "",
            "--- BOUNDARY ---",
            "Inspection: Read-only mounted-filesystem structural state",
            "Raw block-device parsing: No",
            "Repair / scrub / balance / mutation: No",
        ])
        self._summary_text = "\n".join(lines) + "\n"

    def _populate_allocation(self):
        rows = list(self.deep.get("allocation", []))
        columns = list(self.deep.get("allocation_columns", []))
        self._allocation_columns = columns
        self.allocation_table.setSortingEnabled(False)
        self.allocation_table.clear()
        self.allocation_table.setRowCount(len(rows))
        self.allocation_table.setColumnCount(len(columns))
        self.allocation_table.setHorizontalHeaderLabels([label for _key, label in columns])
        for row_index, record in enumerate(rows):
            for col_index, (key, _label) in enumerate(columns):
                value = record.get(key)
                display = _display_value(key, value)
                if isinstance(value, (int, float)):
                    item = NumericTableWidgetItem(display, value)
                else:
                    item = QTableWidgetItem(display)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record)
                self.allocation_table.setItem(row_index, col_index, item)
        self.allocation_table.setSortingEnabled(True)
        provider = self.deep.get("provider", "Unavailable")
        if rows:
            if provider == "ext4":
                self._set_tab_status("allocation", 
                    "ext4 multiblock allocator buddy-cache groups reported by the mounted filesystem."
                )
            elif provider == "XFS":
                self._set_tab_status("allocation", 
                    "XFS allocation groups. 'Unchecked / no conclusion' is not treated as healthy."
                )
            elif provider == "Btrfs":
                self._set_tab_status("allocation", 
                    "Btrfs filesystem-native space classes/profiles; these are not presented as XFS/ext4 groups."
                )
            else:
                self._set_tab_status("allocation", "")
            self._set_tab_status(
                "allocation",
                f"Refreshed {provider} allocation inventory: {len(rows):,} unit(s). "
                + self._allocation_status_base,
            )
            self.allocation_table.selectRow(0)
        else:
            self._set_tab_status("allocation",
                "No filesystem-native allocation-unit rows are available for this selected mount/provider."
            )
            self.allocation_details.clear()
        self._filter_table("allocation")

    def _allocation_selected(self):
        row = self.allocation_table.currentRow()
        if row < 0 or self.allocation_table.isRowHidden(row):
            self.allocation_details.clear()
            self._update_tab_status("allocation")
            return
        item = self.allocation_table.item(row, 0)
        record = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(record, dict):
            self.allocation_details.clear()
            self._update_tab_status("allocation")
            return
        lines = ["--- ALLOCATION UNIT ---"]
        for key, value in record.items():
            if key == "raw_fields":
                continue
            if key == "buddy_counts":
                rendered = ", ".join(f"2^{i}={count}" for i, count in enumerate(value))
            else:
                rendered = _display_value(key, value)
            lines.append(f"{str(key).replace('_', ' ').title()}: {rendered}")
        if isinstance(record.get("raw_fields"), dict) and record["raw_fields"]:
            lines.extend(["", "--- RAW REPORTED FIELDS ---"])
            for key, value in record["raw_fields"].items():
                lines.append(f"{key}: {value}")
        self._replace_info(self.allocation_details, "\n".join(lines) + "\n")
        self._update_tab_status("allocation")

    def acquire_map(self):
        if not self.record:
            return
        self.map_btn.setEnabled(False)
        self._set_tab_status("map", "Collecting read-only physical filesystem map…")
        try:
            rows, status = filesystem_map(self.record, max_records=20000, batch_size=256)
            self.map_rows = rows
            self.map_status = status
            self._populate_map()
        finally:
            self.map_btn.setEnabled(True)

    def _populate_map(self):
        self.map_table.setSortingEnabled(False)
        self.map_table.setRowCount(len(self.map_rows))
        keys = ["device", "physical_start", "length", "owner", "logical_offset", "flags"]
        for row_index, record in enumerate(self.map_rows):
            for col_index, key in enumerate(keys):
                value = record.get(key)
                display = _display_value(key, value)
                if isinstance(value, (int, float)):
                    item = NumericTableWidgetItem(display, value)
                else:
                    item = QTableWidgetItem(display)
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record)
                self.map_table.setItem(row_index, col_index, item)
        self.map_table.setSortingEnabled(True)
        error = (self.map_status or {}).get("error", "")
        if error:
            self._set_tab_status("map", f"Physical map unavailable: {error}")
        elif (self.map_status or {}).get("truncated"):
            self._set_tab_status("map", 
                f"Showing first {len(self.map_rows):,} reported mappings; safety limit reached."
            )
        else:
            self._set_tab_status("map", f"{len(self.map_rows):,} physical filesystem mappings reported.")
        if self.map_rows:
            self.map_table.selectRow(0)
        else:
            self.map_details.clear()
        self._filter_table("map")

    def _map_selected(self):
        row = self.map_table.currentRow()
        if row < 0 or self.map_table.isRowHidden(row):
            self.map_details.clear()
            self._update_tab_status("map")
            return
        item = self.map_table.item(row, 0)
        record = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(record, dict):
            self.map_details.clear()
            self._update_tab_status("map")
            return
        lines = ["--- MAPPING ---"]
        for key, value in record.items():
            lines.append(f"{str(key).replace('_', ' ').title()}: {_display_value(key, value)}")
        lines.extend(["", "Owner values are kernel/API-reported identities; no pathname is inferred."])
        self._replace_info(self.map_details, "\n".join(lines) + "\n")
        self._update_tab_status("map")

    def _export_context(self):
        return {
            "Selected Mount": self.record.get("mount_point", ""),
            "Filesystem Type": self.record.get("fstype", ""),
            "Provider": (self.deep or {}).get("provider", "Unavailable"),
        }

    @staticmethod
    def _append_fields(flat_records, view, records, columns):
        records = list(records or [])
        if not records:
            flat_records.append({
                "view": view, "record": "", "field": "Status",
                "value": "No collected records.",
            })
            return
        for index, record in enumerate(records, 1):
            for key, label in columns:
                if key in record:
                    flat_records.append({
                        "view": view,
                        "record": str(index),
                        "field": label,
                        "value": _display_value(key, record[key]),
                    })
            # Provider-specific raw fields are retained in the export.
            raw = record.get("raw_fields")
            if isinstance(raw, dict):
                for key, value in raw.items():
                    flat_records.append({
                        "view": view, "record": str(index),
                        "field": f"Raw: {key}", "value": _display_value(key, value),
                    })

    def export_selected_views(self, selected, parent=None):
        target = parent or self
        selected = list(selected or [])
        if not selected:
            QMessageBox.information(target, "Export", "Select at least one filesystem view to export.")
            return
        if not self.record or not self.deep:
            QMessageBox.information(target, "Export", "No mounted filesystem is selected.")
            return

        flat_records = []
        if "summary" in selected:
            section = "Filesystem Summary"
            for line in self._summary_text.splitlines():
                if line.startswith("--- ") and line.endswith(" ---"):
                    section = line[4:-4]
                elif ": " in line:
                    key, value = line.split(": ", 1)
                    flat_records.append({
                        "view": f"Summary / {section}", "record": "",
                        "field": key, "value": value,
                    })
                elif line.strip():
                    flat_records.append({
                        "view": f"Summary / {section}", "record": "",
                        "field": "Details", "value": line,
                    })

        if "allocation" in selected:
            self._append_fields(
                flat_records, "Allocation",
                (self.deep or {}).get("allocation", []),
                self._allocation_columns,
            )

        if "map" in selected:
            if self.map_status is None:
                flat_records.append({
                    "view": "Physical Map", "record": "", "field": "Status",
                    "value": "Not collected. Use Map… to acquire physical mappings.",
                })
            else:
                for key, value in self.map_status.items():
                    flat_records.append({
                        "view": "Physical Map", "record": "",
                        "field": f"Map Status: {key}", "value": _display_value(key, value),
                    })
                self._append_fields(
                    flat_records, "Physical Map", self.map_rows,
                    [
                        ("device", "Device"), ("physical_start", "Physical Start"),
                        ("physical_end", "Physical End"), ("length", "Length"),
                        ("owner", "Owner"), ("owner_raw", "Owner Raw"),
                        ("logical_offset", "Logical Offset"), ("flags", "Flags"),
                        ("flags_raw", "Flags Raw"),
                    ],
                )
        export_records_dialog(
            target,
            "Filesystem Details",
            flat_records,
            columns=[
                ("view", "View"),
                ("record", "Record"),
                ("field", "Field"),
                ("value", "Value"),
            ],
            sections=self._export_context(),
        )

    def export_active(self):
        # Compatibility with existing callers: always use Options → Export.
        self.owner.show_options()

    def get_export_records(self):
        if self.tabs.currentIndex() == 0:
            return list((self.deep or {}).get("allocation", []))
        return list(self.map_rows)
