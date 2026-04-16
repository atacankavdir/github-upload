#!/usr/bin/env python3
"""
Build a browser-friendly JSON word list from Excel files in Data/.

This script uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def column_from_ref(ref: str) -> str:
    """Return Excel column letters from a cell reference (for example A12 -> A)."""
    return "".join(char for char in ref if char.isalpha())


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Read shared string table from an .xlsx archive."""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []

    for si in root.findall("m:si", NS):
        # Some cells store rich text split across multiple <t> nodes.
        text_nodes = si.findall(".//m:t", NS)
        strings.append("".join(node.text or "" for node in text_nodes))

    return strings


def first_sheet_path(archive: zipfile.ZipFile) -> str:
    """Resolve the path of the first worksheet in workbook.xml."""
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    first_sheet = workbook.find("m:sheets/m:sheet", NS)
    if first_sheet is None:
        raise ValueError("Workbook has no sheets")

    relation_id = first_sheet.attrib[
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    ]
    target = rel_map[relation_id]
    return target if target.startswith("xl/") else f"xl/{target}"


def cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    """Return text value for one Excel XML cell element."""
    cell_type = cell.attrib.get("t")
    value_node = cell.find("m:v", NS)

    if cell_type == "s" and value_node is not None and value_node.text is not None:
        index = int(value_node.text)
        if 0 <= index < len(shared_strings):
            return shared_strings[index]
        return ""

    if cell_type == "inlineStr":
        text_nodes = cell.findall(".//m:t", NS)
        return "".join(node.text or "" for node in text_nodes)

    if value_node is not None and value_node.text is not None:
        return value_node.text

    return ""


def build_concise_example_sentence(dutch_word: str) -> str:
    """
    Build a short Dutch example sentence for one vocabulary item.

    This keeps generation deterministic and lightweight for large word lists.
    """
    clean_word = dutch_word.strip()
    return f'Ik oefen "{clean_word}".'


def extract_pairs_from_xlsx(xlsx_path: Path) -> list[dict[str, str]]:
    """
    Extract Dutch-English pairs from first worksheet.

    Assumes Dutch is in column A and English is in column B.
    """
    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = load_shared_strings(archive)
        worksheet_path = first_sheet_path(archive)
        worksheet = ET.fromstring(archive.read(worksheet_path))

    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    source_name = xlsx_path.name

    for row in worksheet.findall("m:sheetData/m:row", NS):
        by_column: dict[str, str] = {}
        for cell in row.findall("m:c", NS):
            ref = cell.attrib.get("r", "")
            column = column_from_ref(ref)
            by_column[column] = cell_text(cell, shared_strings).strip()

        dutch = by_column.get("A", "").strip()
        english = by_column.get("B", "").strip()

        # Skip title rows and incomplete rows.
        if not dutch or not english:
            continue
        if dutch.lower().startswith("mock"):
            continue

        key = (dutch.lower(), english.lower())
        if key in seen:
            continue
        seen.add(key)

        pairs.append(
            {
                "dutch": dutch,
                "english": english,
                # Keep examples concise.
                "exampleDutch": build_concise_example_sentence(dutch),
                # Keep the first source file name for quick display/filtering.
                "sourceFile": source_name,
                # Keep full source list in case the same pair appears in many files.
                "sourceFiles": [source_name],
            }
        )

    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build data/words.json from Data/*.xlsx files."
    )
    parser.add_argument(
        "--source-dir",
        default="Data",
        help="Directory containing .xlsx word list files (default: Data)",
    )
    parser.add_argument(
        "--out",
        action="append",
        default=["data/words.json"],
        help="Output JSON path. Can be used multiple times.",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    excel_files = sorted(source_dir.glob("*.xlsx"))

    if not excel_files:
        raise SystemExit(f"No .xlsx files found in {source_dir}")

    all_pairs: list[dict[str, str | list[str]]] = []
    key_to_index: dict[tuple[str, str], int] = {}

    for xlsx_file in excel_files:
        for pair in extract_pairs_from_xlsx(xlsx_file):
            key = (pair["dutch"].lower(), pair["english"].lower())
            existing_index = key_to_index.get(key)

            if existing_index is None:
                key_to_index[key] = len(all_pairs)
                all_pairs.append(pair)
                continue

            # If duplicate appears in another file, keep all sources.
            existing_pair = all_pairs[existing_index]
            existing_sources = existing_pair["sourceFiles"]
            source_name = pair["sourceFile"]

            if isinstance(existing_sources, list) and source_name not in existing_sources:
                existing_sources.append(source_name)

    for out_path_str in args.out:
        out_path = Path(out_path_str)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(all_pairs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(all_pairs)} words -> {out_path}")


if __name__ == "__main__":
    main()
