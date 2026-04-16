#!/usr/bin/env python3
"""
Generate Dutch example sentences in batches and review them in a second pass.

This script is deterministic and uses only the standard library.
It updates data/examples_overrides.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+")

CONTEXT_TOKENS = {
    "werk",
    "kantoor",
    "school",
    "klas",
    "winkel",
    "boodschappen",
    "trein",
    "bus",
    "station",
    "huis",
    "thuis",
    "dokter",
    "huisarts",
    "afspraak",
    "vergadering",
}

BANNED_PATTERNS = (
    "we praten over",
    "ik oefen",
    "het woord",
)

QUESTION_WORDS = {"waarom", "wanneer", "hoe", "wat", "wie", "waar"}

TIME_MARKERS = (
    "vandaag",
    "gisteren",
    "morgen",
    "straks",
    "later",
    "vroeg",
    "laat",
    "week",
    "maand",
    "jaar",
    "overdag",
    "avond",
    "'s avonds",
    "doordeweeks",
    "weekend",
    "op tijd",
)


def normalize_key(dutch: str, english: str) -> str:
    return f"{dutch.strip().lower()}|||{english.strip().lower()}"


def load_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def stable_choice(key: str, options: list[str]) -> str:
    if not options:
        return ""
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(options)
    return options[idx]


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def first_variant(dutch: str) -> str:
    text = dutch.strip()
    if "/" in text:
        left = text.split("/", 1)[0].strip()
        if left:
            return left
    return text


def is_question_term(term: str) -> bool:
    lower = term.lower().strip()
    if lower in QUESTION_WORDS:
        return True
    return lower.startswith("hoe ")


def is_time_term(term: str) -> bool:
    lower = term.lower()
    return any(marker in lower for marker in TIME_MARKERS)


def is_likely_verb(dutch: str, english: str) -> bool:
    d = dutch.lower().strip()
    e = english.lower().strip()
    if e.startswith("to "):
        return True
    # Infinitive-like Dutch verbs often end with -en.
    if " " not in d and d.endswith("en") and len(d) > 3:
        return True
    return False


def is_likely_adjective(dutch: str, english: str) -> bool:
    d = dutch.lower().strip()
    e = english.lower().strip()
    dutch_suffixes = ("ig", "lijk", "baar", "zaam", "loos", "isch", "vrij")
    common_adj = {
        "important",
        "friendly",
        "busy",
        "clean",
        "dirty",
        "special",
        "available",
        "quiet",
        "easy",
        "difficult",
        "cozy",
        "famous",
        "new",
        "open",
        "closed",
        "little",
        "few",
        "enough",
        "simple",
    }
    return d.endswith(dutch_suffixes) or e in common_adj


def is_past_tense_label(english: str) -> bool:
    return "past tense" in english.lower()


def is_quantity_or_ordinal(dutch: str, english: str) -> bool:
    d = dutch.lower().strip()
    e = english.lower().strip()
    if any(ch.isdigit() for ch in d):
        return True
    if d in {"eerste", "tweede", "derde"}:
        return True
    if d in {"weinig", "veel", "minder", "meer", "genoeg"}:
        return True
    if e in {"first", "second", "third", "one time"}:
        return True
    return False


def generate_raw_sentence(dutch: str, english: str, key: str) -> str:
    term = first_variant(dutch)
    lower_term = term.lower()

    # Special handling for common question words/phrases.
    if lower_term == "waarom":
        return "Waarom ben je vandaag te laat op je werk?"
    if lower_term == "wanneer":
        return "Wanneer begint je afspraak bij de huisarts morgen?"
    if lower_term == "hoe vaak":
        return "Hoe vaak ga je met de trein naar kantoor?"
    if lower_term == "hoe duur":
        return "Hoe duur is dat abonnement bij de sportschool?"

    if is_question_term(term):
        return f"{term.capitalize()} ga je morgen naar school of werk?"

    if is_past_tense_label(english):
        return f"In de les oefenen we {term} als verleden tijd."

    if is_quantity_or_ordinal(term, english):
        if any(ch.isdigit() for ch in term):
            return f"Ik heb het maar {term} geprobeerd op mijn werk."
        if lower_term in {"eerste", "tweede", "derde"}:
            return f"Ik ben vandaag als {term} aan de beurt op werk."
        return f"Ik heb {term} tijd voor deze taak op werk."

    if is_time_term(term):
        templates = [
            f"We vertrekken {term} naar de afspraak bij de dokter.",
            f"Ik werk {term} op kantoor en reis met de trein.",
            f"Wij gaan {term} naar huis na het werk.",
        ]
        return stable_choice(key, templates)

    if is_likely_verb(term, english):
        templates = [
            f"Op het werk moet ik {term} voor de lunch.",
            f"Ik wil {term} na de vergadering op kantoor.",
            f"We gaan {term} voordat de trein vertrekt.",
        ]
        return stable_choice(key, templates)

    if is_likely_adjective(term, english):
        templates = [
            f"Op kantoor is de sfeer vandaag {term} in het team.",
            f"De winkel is vandaag {term} door alle klanten.",
            f"De uitleg op school was {term} voor iedereen.",
        ]
        return stable_choice(key, templates)

    templates = [
        f"Ik gebruik {term} op het werk elke dag.",
        f"In de winkel koop ik {term} voor thuis.",
        f"Op school bespreken we {term} tijdens de les.",
        f"In de trein lees ik iets over {term}.",
    ]
    return stable_choice(key, templates)


def has_context_token(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in CONTEXT_TOKENS)


def force_context_sentence(term: str, category: str) -> str:
    if category == "past":
        return f"In de les oefenen we {term} als verleden tijd."
    if category == "quantity":
        if any(ch.isdigit() for ch in term):
            return f"Ik heb het maar {term} geprobeerd op mijn werk."
        if term.lower() in {"eerste", "tweede", "derde"}:
            return f"Ik ben vandaag als {term} aan de beurt op werk."
        return f"Ik heb {term} tijd voor deze taak op werk."
    if category == "verb":
        return f"Op het werk moet ik {term} voor de lunch."
    if category == "adjective":
        return f"Op kantoor is de sfeer vandaag {term} in het team."
    if category == "time":
        return f"We gaan {term} naar de afspraak bij de dokter."
    if category == "question":
        return f"{term.capitalize()} ga je morgen naar school of werk?"
    return f"Ik gebruik {term} op het werk elke dag."


def categorize_term(dutch: str, english: str) -> str:
    term = first_variant(dutch)
    if is_past_tense_label(english):
        return "past"
    if is_quantity_or_ordinal(term, english):
        return "quantity"
    if is_question_term(term):
        return "question"
    if is_time_term(term):
        return "time"
    if is_likely_verb(term, english):
        return "verb"
    if is_likely_adjective(term, english):
        return "adjective"
    return "noun"


def needs_semantic_rewrite(dutch: str, english: str, sentence: str) -> bool:
    term = first_variant(dutch)
    category = categorize_term(dutch, english)
    lower = sentence.lower().strip()

    auto_patterns = (
        "ik gebruik ",
        "in de winkel koop ik ",
        "op school bespreken we ",
        "in de trein lees ik iets over ",
        "op kantoor is de sfeer vandaag ",
    )
    looks_auto = any(lower.startswith(p) for p in auto_patterns)

    if looks_auto:
        return True

    if category == "past" and "verleden tijd" not in lower:
        return True
    if category == "quantity":
        if term.lower() in {"eerste", "tweede", "derde"} and "aan de beurt" not in lower:
            return True
        if any(ch.isdigit() for ch in term) and "maar" not in lower:
            return True
    if category in {"adjective", "past", "quantity"} and looks_auto:
        return True

    return False


def rewrite_problematic_template(dutch: str, sentence: str) -> str | None:
    term = first_variant(dutch)
    lower_sentence = sentence.lower().strip()
    lower_term = term.lower()

    generic_auto_prefixes = (
        "ik gebruik ",
        "in de winkel koop ik ",
        "op school bespreken we ",
        "in de trein lees ik iets over ",
    )

    if lower_sentence.startswith(generic_auto_prefixes):
        return f"Tijdens mijn werk gaat het vaak over {term} vandaag."

    if lower_sentence.startswith("op kantoor is de sfeer vandaag "):
        if lower_term in {"vies"}:
            return f"Na het sporten is mijn shirt {term} van zweet."
        if lower_term in {"geopend", "dicht", "gesloten"}:
            return f"De winkel is vandaag {term} tot zes uur."
        if lower_term in {"beschikbaar"}:
            return f"Ik ben morgen {term} voor een extra afspraak."
        if lower_term in {"voldoende"}:
            return f"Er is {term} tijd voor deze opdracht op school."
        if lower_term in {"vrijwillig"}:
            return f"Hij helpt {term} bij activiteiten in het buurthuis."
        if lower_term in {"schriftelijk"}:
            return f"Je moet je vandaag {term} aanmelden bij de balie."
        if lower_term in {"zo snel mogelijk", "zoveel mogelijk"}:
            return f"Ik wil {term} klaar zijn voor mijn afspraak."
        if lower_term in {"namelijk"}:
            return "Ik kom later, namelijk na mijn afspraak bij de dokter."
        return f"Op het werk is deze taak vandaag {term} voor mij."

    return None


def review_sentence(dutch: str, english: str, sentence: str) -> tuple[str, list[str]]:
    """
    Second pass reviewer:
    - enforce inclusion of target
    - enforce 6-12 words
    - enforce practical context
    - enforce no banned generic patterns
    """
    term = first_variant(dutch)
    category = categorize_term(dutch, english)
    issues: list[str] = []
    rewrote_problematic = False
    text = sentence.strip()

    # Normalize punctuation: keep simple sentence endings.
    text = re.sub(r"[!?]+(?=\.)", "", text)
    if text.endswith("?") or text.endswith("!"):
        text = text[:-1].rstrip()

    if not text.endswith("."):
        text = text.rstrip(".") + "."

    lower = text.lower()
    if any(pattern in lower for pattern in BANNED_PATTERNS):
        issues.append("banned_pattern")

    if term.lower() not in lower:
        issues.append("missing_term")

    wc = word_count(text)
    if wc < 6 or wc > 12:
        issues.append("word_count")

    if needs_semantic_rewrite(dutch, english, text):
        issues.append("semantic_mismatch")
        rewritten = rewrite_problematic_template(dutch, text)
        if rewritten:
            text = rewritten
            rewrote_problematic = True

    if issues and not rewrote_problematic:
        text = force_context_sentence(term, category)
        wc2 = word_count(text)
        if wc2 < 6:
            text = f"Vandaag gebruik ik {term} op mijn werk."
        elif wc2 > 12:
            text = f"Ik gebruik {term} op het werk."

    if not text.endswith("."):
        text += "."

    return text, issues


def migrate_override_keys(
    overrides: dict[str, str],
    typo_corrections: dict[str, dict[str, str]],
) -> tuple[dict[str, str], int]:
    """
    Move old typo keys to corrected keys where applicable.
    """
    migrated: dict[str, str] = {}
    moved_count = 0

    correction_key_map = {
        old_key.lower(): normalize_key(value["dutch"], value["english"])
        for old_key, value in typo_corrections.items()
        if isinstance(value, dict)
        and isinstance(value.get("dutch"), str)
        and isinstance(value.get("english"), str)
    }

    for key, sentence in overrides.items():
        if not isinstance(key, str) or not isinstance(sentence, str):
            continue
        source_key = key.strip().lower()
        target_key = correction_key_map.get(source_key, source_key)
        if target_key != source_key:
            moved_count += 1

        if target_key in migrated:
            # Keep the longer sentence if there is a collision.
            if len(sentence.strip()) > len(migrated[target_key].strip()):
                migrated[target_key] = sentence.strip()
        else:
            migrated[target_key] = sentence.strip()

    return migrated, moved_count


def chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate missing example sentences in reviewed batches."
    )
    parser.add_argument("--words", default="data/words.json")
    parser.add_argument("--overrides", default="data/examples_overrides.json")
    parser.add_argument("--typo-corrections", default="data/typo_corrections.json")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="0 means process all remaining batches.",
    )
    parser.add_argument(
        "--report",
        default="data/example_generation_report.json",
        help="Write per-run report here.",
    )
    parser.add_argument(
        "--review-all",
        action="store_true",
        help="Run second-pass review on all overrides after generation.",
    )
    args = parser.parse_args()

    words_path = Path(args.words)
    overrides_path = Path(args.overrides)
    corrections_path = Path(args.typo_corrections)
    report_path = Path(args.report)

    words = json.loads(words_path.read_text(encoding="utf-8"))
    if not isinstance(words, list):
        raise SystemExit("words file must contain a list")

    overrides = load_json_dict(overrides_path)
    typo_corrections = load_json_dict(corrections_path)

    cleaned_overrides, moved_count = migrate_override_keys(overrides, typo_corrections)

    missing: list[dict] = []
    for word in words:
        dutch = str(word.get("dutch", "")).strip()
        english = str(word.get("english", "")).strip()
        if not dutch or not english:
            continue
        key = normalize_key(dutch, english)
        if key not in cleaned_overrides:
            missing.append({"key": key, "dutch": dutch, "english": english})

    all_batches = chunked(missing, max(1, args.batch_size))
    batches_to_run = all_batches
    if args.max_batches > 0:
        batches_to_run = all_batches[: args.max_batches]

    generated_count = 0
    reviewed_fix_count = 0
    review_all_fix_count = 0
    batch_reports: list[dict] = []

    for idx, batch in enumerate(batches_to_run, start=1):
        batch_generated = 0
        batch_review_fixes = 0
        for item in batch:
            key = item["key"]
            raw = generate_raw_sentence(item["dutch"], item["english"], key)
            reviewed, issues = review_sentence(item["dutch"], item["english"], raw)
            cleaned_overrides[key] = reviewed
            batch_generated += 1
            if issues:
                batch_review_fixes += 1

        generated_count += batch_generated
        reviewed_fix_count += batch_review_fixes
        batch_reports.append(
            {
                "batchNumber": idx,
                "batchSize": batch_generated,
                "reviewFixes": batch_review_fixes,
                "firstKey": batch[0]["key"] if batch else None,
                "lastKey": batch[-1]["key"] if batch else None,
            }
        )

    if args.review_all:
        for word in words:
            dutch = str(word.get("dutch", "")).strip()
            english = str(word.get("english", "")).strip()
            if not dutch or not english:
                continue

            key = normalize_key(dutch, english)
            current = cleaned_overrides.get(key, "")
            if not current:
                continue

            reviewed, issues = review_sentence(dutch, english, current)
            if reviewed != current:
                cleaned_overrides[key] = reviewed
                review_all_fix_count += 1

    overrides_path.write_text(
        json.dumps(dict(sorted(cleaned_overrides.items())), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    final_missing = 0
    for word in words:
        key = normalize_key(str(word.get("dutch", "")), str(word.get("english", "")))
        if key and key not in cleaned_overrides:
            final_missing += 1

    report = {
        "totalWords": len(words),
        "overridesBeforeRaw": len(overrides),
        "overridesAfterMigration": len(cleaned_overrides) - generated_count,
        "movedOverrideKeys": moved_count,
        "missingBeforeGeneration": len(missing),
        "generatedThisRun": generated_count,
        "reviewFixesThisRun": reviewed_fix_count,
        "reviewAllFixes": review_all_fix_count,
        "remainingMissing": final_missing,
        "batchesRun": len(batch_reports),
        "batchReports": batch_reports,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"Generated {generated_count} examples in {len(batch_reports)} batch(es). "
        f"Remaining missing: {final_missing}. Review fixes: {reviewed_fix_count}."
    )
    print(f"Updated overrides -> {overrides_path}")
    print(f"Report -> {report_path}")


if __name__ == "__main__":
    main()
