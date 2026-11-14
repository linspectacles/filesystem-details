#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LinSpectacles - Linux Inspection Suite
# Copyright (C) 2026 brunonlinespace
# GPL-3.0-or-later

import csv
import io
import json
import re
from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem

STANDALONE_STYLESHEET = r"""
QMainWindow, QWidget { background-color: #1e1e1e; color: #dcdcdc; font-family: "Segoe UI", Ubuntu, sans-serif; font-size: 10pt; }
QTabWidget::pane { border: 1px solid #333333; background-color: #1e1e1e; }
QTabBar::tab { background-color: #2d2d2d; color: #aaaaaa; padding: 8px 16px; border: 1px solid #333333; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
QTabBar::tab:selected { background-color: #007acc; color: #ffffff; font-weight: bold; }
QTabBar::tab:hover:!selected { background-color: #3e3e42; color: #ffffff; }
QGroupBox { border: 1px solid #333333; border-radius: 6px; margin-top: 6px; padding-top: 10px; background-color: #252526; }
QLineEdit { background-color: #333333; color: #ffffff; border: 1px solid #454545; border-radius: 4px; padding: 4px 8px; selection-background-color: #007acc; }
QLineEdit:focus { border: 1px solid #007acc; }
QTableWidget { background-color: #1e1e1e; alternate-background-color: #252526; color: #dcdcdc; gridline-color: #2d2d2d; border: 1px solid #333333; border-radius: 4px; }
QTableWidget::item:selected { background-color: #094771; color: #ffffff; }
QHeaderView::section { background-color: #2d2d2d; color: #ffffff; padding: 5px; border: 1px solid #333333; font-weight: bold; }
QPushButton { background-color: #333333; color: #ffffff; border: 1px solid #454545; border-radius: 3px; padding: 4px 8px; }
QPushButton:hover { background-color: #007acc; border-color: #007acc; }
QPushButton:pressed { background-color: #005999; }
QSplitter::handle { background-color: #2d2d2d; height: 3px; }
QScrollBar:vertical, QScrollBar:horizontal { background: #1e1e1e; border: none; width: 10px; height: 10px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #424242; border-radius: 5px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #686868; }
"""


def default_metadata_font():
    font = QFont("Monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    return font


def metadata_font_from_string(serialized):
    if serialized:
        font = QFont()
        try:
            if font.fromString(str(serialized)):
                return font
        except Exception:
            pass
    return default_metadata_font()


def apply_metadata_font(text_edit, serialized=""):
    """Apply a host-selected metadata font to the widget and its document."""
    font = metadata_font_from_string(serialized)
    text_edit.setFont(font)
    text_edit.document().setDefaultFont(font)
    text_edit.setCurrentFont(font)
    return font


def metadata_font_qss(font):
    family = font.family().replace("\\", "\\\\").replace('"', '\\"')
    size = font.pointSizeF() if font.pointSizeF() > 0 else 10.0
    try:
        raw_weight = font.weight()
        weight = int(getattr(raw_weight, "value", raw_weight))
    except Exception:
        weight = 400
    style = "italic" if font.italic() else "normal"
    return (
        f'font-family: "{family}"; font-size: {size:g}pt; '
        f'font-weight: {weight}; font-style: {style};'
    )


class MetadataHighlighter(QSyntaxHighlighter):
    """Path Inspector-compatible metadata: teal keys/sections, orange values."""

    def __init__(self, document):
        super().__init__(document)
        self.key_color = QColor("#4ec9b0")
        self.value_color = QColor("#ce9178")
        self.heading_color = QColor("#dcdcdc")

    def set_colors(self, key_color, value_color, heading_color):
        self.key_color = QColor(key_color)
        self.value_color = QColor(value_color)
        self.heading_color = QColor(heading_color)
        self.rehighlight()

    def highlightBlock(self, text):
        if not text:
            return
        if text.startswith("---"):
            heading = QTextCharFormat()
            heading.setForeground(self.key_color)
            heading.setFontWeight(QFont.Weight.Bold.value)
            self.setFormat(0, len(text), heading)
            return
        colon = text.find(":")
        if colon > 0:
            key = QTextCharFormat()
            key.setForeground(self.key_color)
            key.setFontWeight(QFont.Weight.Bold.value)
            self.setFormat(0, colon + 1, key)
            if colon + 1 < len(text):
                value = QTextCharFormat()
                value.setForeground(self.value_color)
                self.setFormat(colon + 1, len(text) - colon - 1, value)


class NumericTableWidgetItem(QTableWidgetItem):
    def __init__(self, text, raw_val=0):
        super().__init__(text)
        self.raw_val = raw_val

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.raw_val < other.raw_val
        return super().__lt__(other)


def _safe_scalar(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


def _friendly_label(key):
    return str(key).replace("_", " ").strip().title()


def _export_schema(records, columns=None):
    records = list(records or [])
    labels = {}
    order = []
    for column in columns or []:
        key = str(column[0])
        label = str(column[1]) if len(column) > 1 else _friendly_label(key)
        labels[key] = label
        if key not in order:
            order.append(key)

    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if str(key).startswith("_") or _safe_scalar(value) is None:
                continue
            key = str(key)
            if key not in labels:
                labels[key] = _friendly_label(key)
            if key not in order:
                order.append(key)

    clean = []
    for record in records:
        if not isinstance(record, dict):
            continue
        clean_record = {}
        for key in order:
            scalar = _safe_scalar(record.get(key, ""))
            if scalar is not None:
                clean_record[key] = scalar
        clean.append(clean_record)
    return order, labels, clean


def _slug(text):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text).strip()).strip("-")
    return value.lower() or "linspectacles-export"


def _plain_text_export(title, order, labels, records, sections):
    lines = [f"LinSpectacles - {title}", "=" * max(12, len(title) + 12), ""]
    for section_title, section_text in (sections or {}).items():
        lines.extend([str(section_title), "-" * len(str(section_title)), str(section_text).rstrip(), ""])
    lines.append(f"Items: {len(records)}")
    lines.append("")
    for index, record in enumerate(records, start=1):
        lines.append(f"Item {index}")
        lines.append("-" * (5 + len(str(index))))
        for key in order:
            if key in record:
                lines.append(f"{labels.get(key, _friendly_label(key))}: {record.get(key, '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _csv_export(order, labels, records):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([labels.get(key, _friendly_label(key)) for key in order])
    for record in records:
        writer.writerow([record.get(key, "") for key in order])
    return stream.getvalue()


def _markdown_export(title, order, labels, records, sections):
    lines = [f"# {title}", ""]
    for section_title, section_text in (sections or {}).items():
        lines.extend([f"## {section_title}", "", str(section_text).rstrip(), ""])
    if order:
        lines.append("| " + " | ".join(labels.get(key, _friendly_label(key)) for key in order) + " |")
        lines.append("| " + " | ".join("---" for _ in order) + " |")
        for record in records:
            row = []
            for key in order:
                value = str(record.get(key, "")).replace("|", "\\|").replace("\n", "<br>")
                row.append(value)
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("No items.")
    return "\n".join(lines).rstrip() + "\n"


def export_records_dialog(parent, title, records, columns=None, sections=None):
    """Export already-collected applet data. Plain text is the default format."""
    order, labels, clean_records = _export_schema(records, columns)
    filters = (
        "Plain Text (*.txt);;"
        "CSV (*.csv);;"
        "JSON (*.json);;"
        "Markdown (*.md)"
    )
    default_name = f"{_slug(title)}.txt"
    filename, selected_filter = QFileDialog.getSaveFileName(
        parent,
        f"Export {title}",
        default_name,
        filters,
        "Plain Text (*.txt)",
    )
    if not filename:
        return None

    selected_filter = selected_filter or "Plain Text (*.txt)"
    if selected_filter.startswith("CSV"):
        extension = ".csv"
        text = _csv_export(order, labels, clean_records)
    elif selected_filter.startswith("JSON"):
        extension = ".json"
        payload = {"applet": title, "items": clean_records}
        if sections:
            payload["sections"] = {str(k): str(v) for k, v in sections.items()}
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    elif selected_filter.startswith("Markdown"):
        extension = ".md"
        text = _markdown_export(title, order, labels, clean_records, sections)
    else:
        extension = ".txt"
        text = _plain_text_export(title, order, labels, clean_records, sections)

    path = Path(filename).expanduser()
    if not path.suffix:
        path = path.with_suffix(extension)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        QMessageBox.critical(parent, "Export", f"Could not write the export:\n{exc}")
        return None
    return path
