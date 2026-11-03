from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
import pandas as pd


FORMAT_SUFFIXES = {
    "Excel workbook (.xlsx)": ".xlsx",
    "CSV (.csv)": ".csv",
    "TSV (.tsv)": ".tsv",
    "JSON records (.json)": ".json",
    "JSON Lines (.jsonl)": ".jsonl",
}

DELIMITER_VALUES = {
    "Comma (,)": ",",
    "Semicolon (;)": ";",
    "Tab": "\t",
    "Pipe (|)": "|",
}

ENCODING_VALUES = {
    "UTF-8 with BOM": "utf-8-sig",
    "UTF-8": "utf-8",
    "UTF-16": "utf-16",
    "Windows-1252": "cp1252",
}

SUPPORTED_INPUT_SUFFIXES = {
    ".xlsx",
    ".xlsm",
    ".xls",
    ".csv",
    ".tsv",
    ".txt",
    ".json",
    ".jsonl",
    ".ndjson",
}

TABLE_FILE_TYPES = [
    (
        "Supported table files",
        "*.xlsx *.xlsm *.xls *.csv *.tsv *.txt *.json *.jsonl *.ndjson",
    ),
    ("Excel workbooks", "*.xlsx *.xlsm *.xls"),
    ("CSV files", "*.csv"),
    ("TSV / text files", "*.tsv *.txt"),
    ("JSON files", "*.json *.jsonl *.ndjson"),
    ("All files", "*.*"),
]


def suffix_for_format(format_label: str) -> str:
    try:
        return FORMAT_SUFFIXES[format_label]
    except KeyError as exc:
        raise ValueError(f"Unsupported output format: {format_label}") from exc


def format_for_path(path: str | Path) -> str:
    suffix = Path(path).suffix.casefold()
    for label, expected_suffix in FORMAT_SUFFIXES.items():
        if suffix == expected_suffix:
            return label
    return "Excel workbook (.xlsx)"


def ensure_output_suffix(path: str | Path, format_label: str) -> Path:
    output = Path(path)
    expected_suffix = suffix_for_format(format_label)
    if output.suffix.casefold() != expected_suffix:
        output = output.with_suffix(expected_suffix)
    return output


def delimiter_from_label(label: str) -> str:
    try:
        return DELIMITER_VALUES[label]
    except KeyError as exc:
        raise ValueError(f"Unsupported CSV delimiter: {label}") from exc


def encoding_from_label(label: str) -> str:
    try:
        return ENCODING_VALUES[label]
    except KeyError as exc:
        raise ValueError(f"Unsupported text encoding: {label}") from exc


def is_supported_table_file(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in SUPPORTED_INPUT_SUFFIXES


def list_sheet_names(path: str | Path) -> list[str]:
    source = Path(path)
    if source.suffix.casefold() not in {".xlsx", ".xlsm", ".xls"}:
        return []
    try:
        with pd.ExcelFile(source) as workbook:
            return [str(name) for name in workbook.sheet_names]
    except PermissionError:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / source.name
            shutil.copy2(source, temp_path)
            with pd.ExcelFile(temp_path) as workbook:
                return [str(name) for name in workbook.sheet_names]


def _read_excel(
    path: Path,
    sheet_name: str | int,
    max_rows: int | None,
) -> pd.DataFrame:
    engine = "openpyxl" if path.suffix.casefold() in {".xlsx", ".xlsm"} else None
    kwargs: dict[str, object] = {
        "sheet_name": sheet_name,
        "nrows": max_rows,
    }
    if engine:
        kwargs["engine"] = engine
    try:
        return pd.read_excel(path, **kwargs)
    except PermissionError:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / path.name
            shutil.copy2(path, temp_path)
            return pd.read_excel(temp_path, **kwargs)


def _read_delimited(
    path: Path,
    separator: str | None,
    max_rows: int | None,
) -> pd.DataFrame:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252"):
        try:
            return pd.read_csv(
                path,
                sep=separator,
                engine="python" if separator is None else "c",
                encoding=encoding,
                nrows=max_rows,
            )
        except (UnicodeDecodeError, UnicodeError, pd.errors.ParserError) as exc:
            errors.append(f"{encoding}: {exc}")
    raise ValueError(
        f"Could not read {path.name} as delimited text. "
        + " | ".join(errors[-2:])
    )


def read_table_file(
    path: str | Path,
    sheet_name: str | int = 0,
    max_rows: int | None = None,
) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise ValueError(f"Table file does not exist: {source}")
    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError(
            f"Unsupported table format '{suffix or '(none)'}'. "
            "Use XLSX, CSV, TSV, JSON, or JSON Lines."
        )

    if suffix in {".xlsx", ".xlsm", ".xls"}:
        frame = _read_excel(source, sheet_name, max_rows)
    elif suffix == ".csv":
        frame = _read_delimited(source, separator=None, max_rows=max_rows)
    elif suffix in {".tsv", ".txt"}:
        frame = _read_delimited(source, separator="\t", max_rows=max_rows)
    elif suffix in {".jsonl", ".ndjson"}:
        frame = pd.read_json(source, lines=True)
    else:
        frame = pd.read_json(source)

    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f"{source.name} did not resolve to one table.")
    if max_rows is not None and len(frame) > max_rows:
        frame = frame.head(max_rows)
    return frame


def _style_excel_sheet(writer: pd.ExcelWriter, frame: pd.DataFrame, sheet_name: str) -> None:
    worksheet = writer.sheets[sheet_name]
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    header_fill = PatternFill("solid", fgColor="183A2A")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 24

    sample = frame.head(1000)
    for col_idx, column in enumerate(frame.columns, start=1):
        values = sample[column].fillna("").astype(str)
        max_value_length = int(values.map(len).max()) if not values.empty else 0
        width = min(max(max_value_length, len(str(column))) + 2, 60)
        worksheet.column_dimensions[get_column_letter(col_idx)].width = max(10, width)


def write_table_file(
    frame: pd.DataFrame,
    output_path: str | Path,
    *,
    csv_delimiter: str = ",",
    text_encoding: str = "utf-8-sig",
    sheet_name: str = "Data",
) -> Path:
    output = Path(output_path)
    suffix = output.suffix.casefold()
    supported_outputs = set(FORMAT_SUFFIXES.values())
    if suffix not in supported_outputs:
        raise ValueError(
            f"Unsupported output format '{suffix or '(none)'}'. "
            "Use XLSX, CSV, TSV, JSON, or JSON Lines."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    # Commit only a complete export; failed writes leave the previous file intact.
    handle = tempfile.NamedTemporaryFile(dir=output.parent, suffix=suffix, delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        if suffix == ".xlsx":
            safe_sheet_name = (sheet_name or "Data")[:31]
            with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
                frame.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                _style_excel_sheet(writer, frame, safe_sheet_name)
        elif suffix == ".csv":
            frame.to_csv(
                temporary,
                index=False,
                sep=csv_delimiter,
                encoding=text_encoding,
                lineterminator="\n",
            )
        elif suffix == ".tsv":
            frame.to_csv(
                temporary,
                index=False,
                sep="\t",
                encoding=text_encoding,
                lineterminator="\n",
            )
        elif suffix == ".json":
            frame.to_json(
                temporary,
                orient="records",
                indent=2,
                force_ascii=False,
                date_format="iso",
            )
        else:
            frame.to_json(
                temporary,
                orient="records",
                lines=True,
                force_ascii=False,
                date_format="iso",
            )
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
