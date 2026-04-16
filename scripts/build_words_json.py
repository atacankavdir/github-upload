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


def normalize_pair_key(dutch_word: str, english_word: str) -> str:
    """Create a stable key for one Dutch-English pair."""
    return f"{dutch_word.strip().lower()}|||{english_word.strip().lower()}"


def pick_primary_term(dutch_word: str) -> str:
    """
    Pick the first variant when a word includes slash-separated variants.

    Example:
    - "plek/plaats" -> "plek"
    """
    clean = dutch_word.strip()
    if "/" in clean:
        first_part = clean.split("/", 1)[0].strip()
        if first_part:
            return first_part
    return clean


def looks_like_adjective(dutch_word: str, english_word: str) -> bool:
    """Best-effort adjective detection for short context sentence templates."""
    dutch = dutch_word.lower().strip()
    english = english_word.lower().strip()

    dutch_suffixes = ("ig", "lijk", "baar", "zaam", "loos", "isch", "vrij")
    known_english_adjectives = {
        "special",
        "cozy",
        "free",
        "busy",
        "clean",
        "friendly",
        "happy",
        "quiet",
        "new",
        "important",
        "enough",
        "different",
        "simple",
        "calm",
        "difficult",
        "easy",
        "closed",
        "open",
        "available",
        "normal",
    }

    if dutch.endswith(dutch_suffixes):
        return True
    return english in known_english_adjectives


def looks_like_time_or_adverb_phrase(dutch_word: str) -> bool:
    """Detect common time/adverb expressions for a better sentence frame."""
    text = dutch_word.lower().strip()
    markers = (
        "vandaag",
        "gisteren",
        "morgen",
        "straks",
        "week",
        "maand",
        "jaar",
        "altijd",
        "nooit",
        "eerder",
        "later",
        "vaker",
        "doordeweeks",
        "weekend",
        "op tijd",
        "zo snel mogelijk",
    )
    return any(marker in text for marker in markers)


def looks_like_verb(dutch_word: str, english_word: str) -> bool:
    """
    Best-effort verb detection.

    Priority:
    - English starts with "to "
    - Dutch infinitive-like single word ending in "en"
    """
    english = english_word.lower().strip()
    dutch = dutch_word.lower().strip()

    if english.startswith("to "):
        return True

    if " " not in dutch and dutch.endswith("en") and len(dutch) > 3:
        return True

    return False


def build_context_example_sentence(dutch_word: str, english_word: str) -> str:
    """
    Build a short Dutch context sentence for one vocabulary item.

    This remains deterministic, concise, and safer than fully free-form generation.
    """
    term = pick_primary_term(dutch_word)

    if looks_like_time_or_adverb_phrase(term):
        return f"Ik doe dat {term}."

    if looks_like_verb(term, english_word):
        return f"Ik wil {term}."

    if looks_like_adjective(term, english_word):
        return f"Dat is {term}."

    return f"We praten over {term}."


def load_example_overrides(path: Path) -> dict[str, str]:
    """
    Load manual example sentence overrides keyed by:
    "dutch|||english" (both lowercased).
    """
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
    except Exception:
        return {}

    overrides: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        clean_value = value.strip()
        if not clean_value:
            continue
        overrides[key.strip().lower()] = clean_value

    return overrides


def load_typo_corrections(path: Path) -> dict[str, dict[str, str]]:
    """
    Load typo corrections keyed by:
    "dutch|||english" (both lowercased).

    Value format:
    {
      "dutch": "...",
      "english": "..."
    }
    """
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
    except Exception:
        return {}

    corrections: dict[str, dict[str, str]] = {}

    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue

        corrected_dutch = value.get("dutch")
        corrected_english = value.get("english")

        if not isinstance(corrected_dutch, str) or not isinstance(corrected_english, str):
            continue

        corrected_dutch = corrected_dutch.strip()
        corrected_english = corrected_english.strip()

        if not corrected_dutch or not corrected_english:
            continue

        corrections[key.strip().lower()] = {
            "dutch": corrected_dutch,
            "english": corrected_english,
        }

    return corrections


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
    parser.add_argument(
        "--examples-overrides",
        default="data/examples_overrides.json",
        help=(
            "Optional JSON file with manual example overrides keyed by "
            "'dutch|||english' (default: data/examples_overrides.json)"
        ),
    )
    parser.add_argument(
        "--typo-corrections",
        default="data/typo_corrections.json",
        help=(
            "Optional JSON file with typo corrections keyed by "
            "'dutch|||english' (default: data/typo_corrections.json)"
        ),
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    excel_files = sorted(source_dir.glob("*.xlsx"))
    example_overrides = load_example_overrides(Path(args.examples_overrides))
    typo_corrections = load_typo_corrections(Path(args.typo_corrections))

    if not excel_files:
        raise SystemExit(f"No .xlsx files found in {source_dir}")

    all_pairs: list[dict[str, str | list[str]]] = []
    key_to_index: dict[tuple[str, str], int] = {}

    for xlsx_file in excel_files:
        for pair in extract_pairs_from_xlsx(xlsx_file):
            original_dutch = pair["dutch"]
            original_english = pair["english"]
            original_key = normalize_pair_key(original_dutch, original_english)

            # Apply typo correction before dedupe and before example merge.
            correction = typo_corrections.get(original_key)
            if correction:
                pair["dutch"] = correction["dutch"]
                pair["english"] = correction["english"]

            key = (pair["dutch"].lower(), pair["english"].lower())
            existing_index = key_to_index.get(key)

            if existing_index is None:
                corrected_key = normalize_pair_key(pair["dutch"], pair["english"])
                if corrected_key in example_overrides:
                    pair["exampleDutch"] = example_overrides[corrected_key]
                elif original_key in example_overrides:
                    # Backward compatibility: preserve old overrides while typos are being corrected.
                    pair["exampleDutch"] = example_overrides[original_key]
                else:
                    pair["exampleDutch"] = build_context_example_sentence(
                        pair["dutch"], pair["english"]
                    )

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
