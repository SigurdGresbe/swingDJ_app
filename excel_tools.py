from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from table_io import SUPPORTED_INPUT_SUFFIXES, read_table_file, write_table_file


COLUMN_ALIASES = {
    "Track Name": {"track name", "track", "song", "title", "name"},
    "Artist(s)": {"artist(s)", "artist", "artists"},
    "KOD": {"kod", "kode", "code", "id", "takt"},
    "Playlist": {"playlist"},
    "Played": {"played", "played?"},
}

ALIAS_LOOKUP = {
    alias: canonical
    for canonical, aliases in COLUMN_ALIASES.items()
    for alias in aliases
}


@dataclass(slots=True)
class MergeOptions:
    key_columns: list[str]
    update_mode: str = "fill_blanks"
    include_new_columns: bool = True
    inject_playlist_from_filename: bool = True
    preview_limit: int = 75
    csv_delimiter: str = ","
    text_encoding: str = "utf-8-sig"


@dataclass(slots=True)
class MergeSummary:
    rows_read_source: int = 0
    rows_read_master: int = 0
    rows_added: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    files_processed: int = 0
    duplicate_master_keys: int = 0
    new_columns_added: list[str] = field(default_factory=list)
    preview_rows: list[dict[str, object]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    output_path: str | None = None
    preview_limit: int = 75

    def add_preview(
        self,
        action: str,
        source_name: str,
        row_data: dict[str, object],
        updated_columns: list[str] | None = None,
    ) -> None:
        if len(self.preview_rows) >= self.preview_limit:
            return
        preview = {
            "action": action,
            "source_file": source_name,
            "Track Name": row_data.get("Track Name", ""),
            "Artist(s)": row_data.get("Artist(s)", ""),
            "KOD": row_data.get("KOD", ""),
            "Playlist": row_data.get("Playlist", ""),
            "updated_columns": ", ".join(updated_columns or []),
        }
        self.preview_rows.append(preview)


def parse_sheet_name(value: str | int | None) -> str | int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    sheet_value = str(value).strip()
    if not sheet_value:
        return 0
    if sheet_value.isdigit():
        return int(sheet_value)
    return sheet_value


def read_excel_resilient(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    return read_table_file(path, sheet_name=sheet_name)


def load_workbook_frame(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    df = read_excel_resilient(path, sheet_name=sheet_name)
    if not isinstance(df, pd.DataFrame):
        raise ValueError(f"{path.name} did not resolve to a single sheet.")
    return canonicalize_columns(df)


def canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map: dict[object, str] = {}
    for column in df.columns:
        clean_name = str(column).strip()
        canonical = ALIAS_LOOKUP.get(clean_name.casefold(), clean_name)
        rename_map[column] = canonical
    return df.rename(columns=rename_map)


def is_blank(value: object) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def normalized_text(value: object) -> str:
    if is_blank(value):
        return ""
    return str(value).strip().casefold()


def values_equal(left: object, right: object) -> bool:
    if is_blank(left) and is_blank(right):
        return True
    return normalized_text(left) == normalized_text(right)


def build_row_key(row: pd.Series, key_columns: list[str]) -> tuple[str, ...] | None:
    values: list[str] = []
    for column in key_columns:
        if column not in row.index:
            return None
        value = row.get(column)
        if is_blank(value):
            return None
        values.append(normalized_text(value))
    return tuple(values)


def ensure_key_columns(df: pd.DataFrame, key_columns: list[str], label: str) -> None:
    missing = [column for column in key_columns if column not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing key column(s): {', '.join(missing)}")


def prepare_source_frame(
    df: pd.DataFrame,
    source_name: str,
    inject_playlist_from_filename: bool,
) -> pd.DataFrame:
    prepared = df.copy()
    if inject_playlist_from_filename:
        if "Playlist" not in prepared.columns:
            prepared["Playlist"] = source_name
        else:
            blank_mask = prepared["Playlist"].apply(is_blank)
            prepared.loc[blank_mask, "Playlist"] = source_name
    return prepared


def create_empty_master(key_columns: list[str]) -> pd.DataFrame:
    base_columns = list(dict.fromkeys([*key_columns, "Playlist", "KOD"]))
    return pd.DataFrame(columns=base_columns)


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    prepared = df.copy()
    for column in columns:
        if column not in prepared.columns:
            prepared[column] = pd.NA
    return prepared[columns]


def index_master_keys(
    master_df: pd.DataFrame,
    key_columns: list[str],
) -> tuple[dict[tuple[str, ...], int], int]:
    index: dict[tuple[str, ...], int] = {}
    duplicates = 0
    for idx, row in master_df.iterrows():
        key = build_row_key(row, key_columns)
        if key is None:
            continue
        if key in index:
            duplicates += 1
            continue
        index[key] = idx
    return index, duplicates


def merge_frames(
    master_df: pd.DataFrame,
    source_df: pd.DataFrame,
    options: MergeOptions,
    source_name: str,
    summary: MergeSummary,
) -> pd.DataFrame:
    ensure_key_columns(source_df, options.key_columns, f"Source file '{source_name}'")
    if master_df.empty:
        master_df = create_empty_master(options.key_columns)
    ensure_key_columns(master_df, options.key_columns, "Master list")

    merged = master_df.copy()
    source = prepare_source_frame(
        source_df,
        source_name=source_name,
        inject_playlist_from_filename=options.inject_playlist_from_filename,
    )

    target_columns = list(merged.columns)
    if not target_columns:
        target_columns = list(source.columns)

    if options.include_new_columns:
        for column in source.columns:
            if column not in target_columns:
                target_columns.append(column)
                if column not in summary.new_columns_added:
                    summary.new_columns_added.append(column)

    merged = ensure_columns(merged, target_columns)
    usable_source_columns = [column for column in source.columns if column in merged.columns]

    key_index, duplicates = index_master_keys(merged, options.key_columns)
    summary.duplicate_master_keys += duplicates

    for _, source_row in source.iterrows():
        summary.rows_read_source += 1
        key = build_row_key(source_row, options.key_columns)
        if key is None:
            summary.rows_skipped += 1
            continue

        row_snapshot = {column: source_row.get(column, pd.NA) for column in usable_source_columns}
        if key in key_index:
            if options.update_mode == "add_only":
                continue

            target_idx = key_index[key]
            updated_columns: list[str] = []

            for column in usable_source_columns:
                source_value = source_row.get(column, pd.NA)
                if is_blank(source_value):
                    continue

                target_value = merged.at[target_idx, column]
                should_update = False
                if options.update_mode == "fill_blanks":
                    should_update = is_blank(target_value)
                elif options.update_mode == "overwrite":
                    should_update = not values_equal(target_value, source_value)

                if should_update:
                    merged.at[target_idx, column] = source_value
                    updated_columns.append(column)

            if updated_columns:
                summary.rows_updated += 1
                summary.add_preview("updated", source_name, row_snapshot, updated_columns)
            continue

        new_row = {column: pd.NA for column in merged.columns}
        for column in usable_source_columns:
            new_row[column] = source_row.get(column, pd.NA)
        merged = pd.concat([merged, pd.DataFrame([new_row])], ignore_index=True)
        key_index[key] = len(merged) - 1
        summary.rows_added += 1
        summary.add_preview("added", source_name, row_snapshot)

    return merged


def merge_excel_into_master(
    source_path: str | Path,
    master_path: str | Path,
    output_path: str | Path,
    options: MergeOptions,
    source_sheet: str | int = 0,
    master_sheet: str | int = 0,
    preview_only: bool = False,
) -> MergeSummary:
    source_file = Path(source_path)
    master_file = Path(master_path)
    output_file = Path(output_path)

    source_df = load_workbook_frame(source_file, parse_sheet_name(source_sheet))
    master_df = load_workbook_frame(master_file, parse_sheet_name(master_sheet))

    summary = MergeSummary(
        rows_read_master=len(master_df),
        files_processed=1,
        preview_limit=options.preview_limit,
        messages=[
            f"Source file: {source_file.name}",
            f"Master file: {master_file.name}",
        ],
    )

    merged = merge_frames(
        master_df=master_df,
        source_df=source_df,
        options=options,
        source_name=source_file.stem,
        summary=summary,
    )

    if not preview_only:
        write_table_file(
            merged,
            output_file,
            csv_delimiter=options.csv_delimiter,
            text_encoding=options.text_encoding,
            sheet_name="Merged List",
        )
        summary.output_path = str(output_file)
        summary.messages.append(f"Created merged copy: {output_file}")

    return summary


def build_master_from_folder(
    source_dir: str | Path,
    output_path: str | Path,
    options: MergeOptions,
    template_path: str | Path | None = None,
    source_sheet: str | int = 0,
    template_sheet: str | int = 0,
    skip_filenames: list[str] | None = None,
    preview_only: bool = False,
) -> MergeSummary:
    folder = Path(source_dir)
    output_file = Path(output_path)
    template_file = Path(template_path) if template_path else None
    skip_set = {name.strip() for name in (skip_filenames or []) if name.strip()}

    if not folder.exists():
        raise ValueError(f"Source folder does not exist: {folder}")

    if template_file and template_file.exists():
        master_df = load_workbook_frame(template_file, parse_sheet_name(template_sheet))
        summary = MergeSummary(
            rows_read_master=len(master_df),
            preview_limit=options.preview_limit,
            messages=[f"Starting from template: {template_file.name}"],
        )
    else:
        master_df = create_empty_master(options.key_columns)
        summary = MergeSummary(
            messages=["Starting from an empty master list."],
            preview_limit=options.preview_limit,
        )

    workbook_files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.casefold() in SUPPORTED_INPUT_SUFFIXES
        and path.name not in skip_set
    )
    if template_file and template_file.exists():
        workbook_files = [path for path in workbook_files if path.resolve() != template_file.resolve()]
    if output_file.exists():
        workbook_files = [path for path in workbook_files if path.resolve() != output_file.resolve()]

    if not workbook_files:
        raise ValueError(
            "No XLSX, CSV, TSV, JSON, or JSON Lines files matched the selected folder and skip rules."
        )

    for workbook in workbook_files:
        source_df = load_workbook_frame(workbook, parse_sheet_name(source_sheet))
        master_df = merge_frames(
            master_df=master_df,
            source_df=source_df,
            options=options,
            source_name=workbook.stem,
            summary=summary,
        )
        summary.files_processed += 1

    if not preview_only:
        write_table_file(
            master_df,
            output_file,
            csv_delimiter=options.csv_delimiter,
            text_encoding=options.text_encoding,
            sheet_name="Master List",
        )
        summary.output_path = str(output_file)
        summary.messages.append(f"Created batch master copy: {output_file}")

    return summary

