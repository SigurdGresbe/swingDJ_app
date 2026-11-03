from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Property,
    Qt,
    Signal,
    Slot,
    QTimer,
)

import tempo_store
import field_store

from table_io import list_sheet_names, read_table_file, write_table_file


DISPLAY_ROLE = Qt.ItemDataRole.UserRole + 1
BACKGROUND_ROLE = Qt.ItemDataRole.UserRole + 2
FOREGROUND_ROLE = Qt.ItemDataRole.UserRole + 3
NUMERIC_ROLE = Qt.ItemDataRole.UserRole + 4
RAW_ROLE = Qt.ItemDataRole.UserRole + 5
EDITED_ROLE = Qt.ItemDataRole.UserRole + 6


LIGHT_STYLE_COLORS = (
    "#DCEFE4",
    "#DCE9F2",
    "#F3E6C8",
    "#F2D9D2",
    "#D7ECEB",
    "#E8DEF2",
    "#E5ECCD",
    "#F1DFCC",
)

DARK_STYLE_COLORS = (
    "#244637",
    "#263F53",
    "#504125",
    "#533532",
    "#294A49",
    "#443852",
    "#3A4729",
    "#51402F",
)


class SongTableModel(QAbstractTableModel):
    columnsChanged = Signal()
    summaryChanged = Signal()
    currentFileChanged = Signal()
    sortChanged = Signal()
    filterChanged = Signal()
    updatingChanged = Signal()
    rolesChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._source = pd.DataFrame()
        self._row_keys = {}
        self._field_data = {"edits": {}, "originals": {}}
        self._tempo_edits = {}
        self._view = pd.DataFrame()
        self._visible_columns: list[str] = []
        self._hidden_columns: set[str] = set()
        self._filter_column = "All columns"
        self._filter_text = ""
        self._missing_tempo_only = False
        self._case_sensitive = False
        self._sort_column = ""
        self._sort_ascending = True
        self._style_column = ""
        self._difficulty_column = ""
        self._color_styles = True
        self._color_difficulty = True
        self._highlight_blanks = False
        self._dark_theme = False
        self._current_file = ""
        self._sheet_names: list[str] = []
        self._style_color_map: dict[str, str] = {}
        self._difficulty_min: float | None = None
        self._difficulty_max: float | None = None
        self._hidden_style_tags: set[str] = set()
        self._hidden_theme_tags: set[str] = set()
        self._isolated_tags: set[tuple[str, str]] = set()
        self._isolate_tags = False
        self._kod_range_enabled = False
        self._kod_min = 0.0
        self._kod_max = 200.0
        self._tag_names: dict[str, list[str]] = {}
        self._allowed_tags = {}
        self._updating = False
        self._tag_update_timer = QTimer(self)
        self._tag_update_timer.setSingleShot(True)
        self._tag_update_timer.setInterval(100)
        self._tag_update_timer.timeout.connect(self._apply_view)

    def roleNames(self) -> dict[int, bytes]:
        return {
            DISPLAY_ROLE: b"display",
            BACKGROUND_ROLE: b"cellBackground",
            FOREGROUND_ROLE: b"cellForeground",
            NUMERIC_ROLE: b"numericCell",
            RAW_ROLE: b"rawValue",
            EDITED_ROLE: b"cellEdited",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._view)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible_columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        value = self._view.iloc[index.row(), index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, DISPLAY_ROLE):
            return self._display_value(value)
        if role == EDITED_ROLE:
            row_index = self._view.index[index.row()]
            column = self._visible_columns[index.column()]
            key = self._row_keys.get(row_index, "")
            return (column in self._field_data["edits"].get(key, {}) or
                    column.casefold() in {"bpm", "kod"} and tempo_store.key(tempo_store.song(self._source.loc[row_index].to_dict())) in self._tempo_edits)
        if role == RAW_ROLE:
            return None if self._is_blank(value) else value
        if role == BACKGROUND_ROLE:
            return self._cell_background(index.row(), index.column(), value)
        if role == FOREGROUND_ROLE:
            fill = self._cell_background(index.row(), index.column(), value)
            return self._foreground_for_fill(fill)
        if role == NUMERIC_ROLE:
            return self._is_numeric_value(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return (
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if self._is_numeric_value(value)
                else int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            )
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if not 0 <= section < len(self._visible_columns):
                return None
            column = self._visible_columns[section]
            if column == self._sort_column:
                return f"{column}  {'^' if self._sort_ascending else 'v'}"
            return column
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self._visible_columns[index.column()].casefold() == "spotify uri":
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        source_index = self._view.index[index.row()]
        self._tag_names.clear()
        column = self._visible_columns[index.column()]
        if column.casefold() == "spotify uri":
            return False
        if column.casefold() in {"style", "theme"}:
            result = self.validateTagEdit(column, str(value))
            if not result["valid"]:
                return False
            value = result["value"]
        if column.casefold() in ("bpm", "kod"):
            try:
                tempo_store.correct(tempo_store.song(self._source.loc[source_index].to_dict()), str(value), column.upper())
            except (ValueError, OSError):
                return False
        else:
            try:
                field_store.edit(self._row_keys[source_index], column, str(value))
            except (ValueError, OSError):
                return False
        self._field_data = field_store.load()
        self._tempo_edits = tempo_store.load()["corrections"]
        self._source[column] = self._source[column].astype(object)
        self._source.at[source_index, column] = value
        if column.casefold() in ("bpm", "kod"):
            self._source = tempo_store.apply(self._source)
        self._apply_view()
        return True

    @staticmethod
    def _unique_column_names(columns: Any) -> list[str]:
        counts: dict[str, int] = {}
        unique: list[str] = []
        for value in columns:
            name = str(value).strip() or "Unnamed"
            counts[name] = counts.get(name, 0) + 1
            unique.append(name if counts[name] == 1 else f"{name} [{counts[name]}]")
        return unique

    @staticmethod
    def _detect_column(columns: list[str], candidates: tuple[str, ...]) -> str:
        folded = {column.casefold(): column for column in columns}
        for candidate in candidates:
            if candidate in folded:
                return folded[candidate]
        for candidate in candidates:
            for column in columns:
                if candidate in column.casefold():
                    return column
        return ""

    @staticmethod
    def _is_blank(value: object) -> bool:
        try:
            missing = pd.isna(value)
            if isinstance(missing, bool) and missing:
                return True
        except (TypeError, ValueError):
            return False
        return isinstance(value, str) and not value.strip()

    @staticmethod
    def _is_numeric_value(value: object) -> bool:
        if SongTableModel._is_blank(value) or isinstance(value, bool):
            return False
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _display_value(value: object) -> str:
        if SongTableModel._is_blank(value):
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        text = str(value).replace("\r", " ").replace("\n", " ")
        return text if len(text) <= 180 else text[:177] + "..."

    def set_frame(
        self,
        frame: pd.DataFrame,
        path: str = "",
        sheet_names: list[str] | None = None,
        *, remember_originals: bool = True,
    ) -> None:
        raw = frame.reset_index(drop=True).copy()
        raw.columns = self._unique_column_names(raw.columns)
        if remember_originals:
            field_store.remember(raw, path)
        self._row_keys = {index: field_store.identity(record.to_dict(), path, index) for index, record in raw.iterrows()}
        self._field_data = field_store.load()
        self._tempo_edits = tempo_store.load()["corrections"]
        self._allowed_tags = {}
        for column in raw.columns:
            if column.casefold() in {"style", "theme"}:
                values = list(raw[column])
                for key in self._row_keys.values():
                    values.append(self._field_data["originals"].get(key, {}).get(column, ""))
                    values.append(self._field_data["edits"].get(key, {}).get(column, ""))
                unique = {}
                for value in values:
                    for tag in self._split_tags(value):
                        unique.setdefault(tag.casefold(), tag)
                self._allowed_tags[column.casefold()] = sorted(unique.values(), key=str.casefold)
        prepared = tempo_store.apply(field_store.apply(raw, path)).reset_index(drop=True)
        self._tag_names.clear()
        self._tag_update_timer.stop()
        self._set_updating(False)
        prepared.columns = self._unique_column_names(prepared.columns)
        self.beginResetModel()
        self._source = prepared
        self._current_file = path
        self._sheet_names = list(sheet_names or [])
        columns = [str(column) for column in prepared.columns]
        self._hidden_columns.intersection_update(columns)
        self._visible_columns = [
            column for column in columns if column not in self._hidden_columns
        ]
        if self._style_column not in columns:
            self._style_column = self._detect_column(
                columns,
                ("dance style", "style", "dance genre", "genre", "playlist", "dance"),
            )
        if self._difficulty_column not in columns:
            self._difficulty_column = self._detect_column(
                columns,
                ("difficulty", "challenge", "level", "rating", "sure?"),
            )
        if self._filter_column not in columns:
            self._filter_column = "All columns"
        if self._sort_column not in columns:
            self._sort_column = ""
        self._view = self._build_view()
        self._refresh_color_metadata()
        self.endResetModel()
        self.columnsChanged.emit()
        self.summaryChanged.emit()
        self.currentFileChanged.emit()
        self.sortChanged.emit()
        self.filterChanged.emit()

    def load_file(
        self,
        path: str,
        sheet_name: str | int = 0,
        max_rows: int = 2000,
    ) -> None:
        source = Path(path)
        frame = read_table_file(source, sheet_name=sheet_name, max_rows=max_rows)
        self.set_frame(frame, str(source), list_sheet_names(source))

    def _build_view(self) -> pd.DataFrame:
        frame = self._source
        if self._missing_tempo_only:
            frame = frame.loc[self._missing_tempo_mask(frame)]
        if self._kod_range_enabled:
            column = next((name for name in frame.columns if str(name).casefold() == "kod"), None)
            bpm_column = next((name for name in frame.columns if str(name).casefold() == "bpm"), None)
            tempos = pd.to_numeric(frame[column], errors="coerce") if column else pd.Series(float("nan"), index=frame.index)
            if bpm_column:
                tempos = tempos.fillna(pd.to_numeric(frame[bpm_column], errors="coerce").map(lambda value: tempo_store.kod_from_bpm(value) if pd.notna(value) else float("nan")))
            frame = frame.loc[tempos.between(self._kod_min, self._kod_max)]
        if self._isolate_tags:
            selected = pd.Series(False, index=frame.index)
            for column in ("Style", "Theme"):
                wanted = {tag for kind, tag in self._isolated_tags if kind == column}
                if column in frame and wanted:
                    selected |= frame[column].map(lambda value: bool(wanted.intersection(
                        tag.casefold() for tag in self._split_tags(value))))
            frame = frame.loc[selected]
        for column, hidden in (
            ("Style", self._hidden_style_tags),
            ("Theme", self._hidden_theme_tags),
        ):
            if column in frame.columns and hidden and not self._isolate_tags:
                folded_hidden = {tag.casefold() for tag in hidden}
                visible = frame[column].fillna("").astype(str).map(
                    lambda value: not folded_hidden.intersection(
                        tag.casefold() for tag in self._split_tags(value)
                    )
                )
                frame = frame.loc[visible]
        if self._filter_text:
            columns = (
                list(self._source.columns)
                if self._filter_column == "All columns"
                else [self._filter_column]
                if self._filter_column in self._source.columns
                else []
            )
            if columns:
                masks = [
                    frame[column]
                    .fillna("")
                    .astype(str)
                    .str.contains(
                        self._filter_text,
                        case=self._case_sensitive,
                        regex=False,
                        na=False,
                    )
                    for column in columns
                ]
                combined = masks[0]
                for mask in masks[1:]:
                    combined = combined | mask
                frame = frame.loc[combined]
            else:
                frame = frame.iloc[0:0]

        if self._sort_column and self._sort_column in frame.columns and not frame.empty:
            series = frame[self._sort_column]
            missing = series.map(self._is_blank)
            numeric = pd.to_numeric(series, errors="coerce")
            nonblank_count = int((~missing).sum())
            numeric_count = int(numeric.notna().sum())
            sort_values = (
                numeric
                if nonblank_count and numeric_count >= max(1, round(nonblank_count * 0.8))
                else series.fillna("").astype(str).str.casefold()
            )
            sortable = frame.copy()
            sortable["__qt_missing"] = missing.to_numpy()
            sortable["__qt_sort"] = sort_values.to_numpy()
            sortable["__qt_order"] = range(len(sortable))
            frame = sortable.sort_values(
                by=["__qt_missing", "__qt_sort", "__qt_order"],
                ascending=[True, self._sort_ascending, True],
                kind="mergesort",
            ).drop(columns=["__qt_missing", "__qt_sort", "__qt_order"])

        columns = [
            column for column in self._visible_columns if column in frame.columns
        ]
        return frame.loc[:, columns]

    def _apply_view(self) -> None:
        self._tag_update_timer.stop()
        self.beginResetModel()
        self._view = self._build_view()
        self._refresh_color_metadata()
        self.endResetModel()
        self.summaryChanged.emit()
        self.sortChanged.emit()
        self.filterChanged.emit()
        self._set_updating(False)

    @Property(bool, notify=updatingChanged)
    def updating(self) -> bool:
        return self._updating

    def _set_updating(self, value: bool) -> None:
        if value != self._updating:
            self._updating = value
            self.updatingChanged.emit()

    def _schedule_tag_update(self) -> None:
        self._set_updating(True)
        self.filterChanged.emit()
        # Let the controls and status paint, and combine rapid clicks into one rebuild.
        self._tag_update_timer.start()

    def _refresh_color_metadata(self) -> None:
        self._style_color_map = {}
        if self._style_column in self._view.columns:
            categories = sorted(
                {
                    str(value).strip()
                    for value in self._view[self._style_column]
                    if not self._is_blank(value)
                },
                key=str.casefold,
            )
            palette = DARK_STYLE_COLORS if self._dark_theme else LIGHT_STYLE_COLORS
            self._style_color_map = {
                category: palette[index % len(palette)]
                for index, category in enumerate(categories)
            }
        self._difficulty_min = None
        self._difficulty_max = None
        if self._difficulty_column in self._view.columns:
            numeric = pd.to_numeric(
                self._view[self._difficulty_column],
                errors="coerce",
            )
            if int(numeric.notna().sum()) >= 2:
                self._difficulty_min = float(numeric.min())
                self._difficulty_max = float(numeric.max())

    def _cell_background(self, row: int, column: int, value: object) -> str:
        column_name = self._visible_columns[column]
        if self._highlight_blanks and self._is_blank(value):
            return "#5A3033" if self._dark_theme else "#F8DADB"
        if self._color_styles and column_name == self._style_column and not self._is_blank(value):
            return self._style_color_map.get(str(value).strip(), self._row_color(row))
        if (
            self._color_difficulty
            and column_name == self._difficulty_column
            and not self._is_blank(value)
        ):
            return self._difficulty_color(value)
        return self._row_color(row)

    def _row_color(self, row: int) -> str:
        if self._dark_theme:
            return "#222825" if row % 2 else "#1C211E"
        return "#F8F5EF" if row % 2 else "#FFFFFF"

    def _difficulty_color(self, value: object) -> str:
        easy = "#28513F" if self._dark_theme else "#D9EFE2"
        medium = "#5B4925" if self._dark_theme else "#F5E7BE"
        hard = "#5C3335" if self._dark_theme else "#F4D6D2"
        unknown = "#34414D" if self._dark_theme else "#DFE7EC"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            text = str(value).strip().casefold()
            if any(token in text for token in ("easy", "beginner", "simple", "low")):
                return easy
            if any(token in text for token in ("medium", "intermediate", "normal")):
                return medium
            if any(token in text for token in ("hard", "advanced", "expert", "high")):
                return hard
            return unknown

        if self._difficulty_min is None or self._difficulty_max is None:
            return medium
        span = self._difficulty_max - self._difficulty_min
        ratio = 0.5 if math.isclose(span, 0.0) else (numeric - self._difficulty_min) / span
        if ratio <= 0.33:
            return easy
        if ratio <= 0.66:
            return medium
        return hard

    @staticmethod
    def _foreground_for_fill(fill: str) -> str:
        normalized = fill.lstrip("#")
        if len(normalized) != 6:
            return "#1E2723"
        red, green, blue = (
            int(normalized[0:2], 16),
            int(normalized[2:4], 16),
            int(normalized[4:6], 16),
        )
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return "#18201C" if luminance > 155 else "#F7F5F0"

    @staticmethod
    def _split_tags(value: object) -> list[str]:
        if SongTableModel._is_blank(value):
            return []
        return [tag.strip() for tag in str(value).split(";") if tag.strip()]

    def _tag_states(self, column: str, hidden: set[str]) -> list[dict[str, object]]:
        if column not in self._source.columns:
            return []
        if column not in self._tag_names:
            self._tag_names[column] = sorted({
                tag for value in self._source[column]
                for tag in self._split_tags(value)
            }, key=str.casefold)
        folded_hidden = {tag.casefold() for tag in hidden}
        return [
            {"name": tag, "visible": (column, tag.casefold()) in self._isolated_tags
             if self._isolate_tags else tag.casefold() not in folded_hidden}
            for tag in self._tag_names[column]
        ]

    @Property(list, notify=columnsChanged)
    def allColumns(self) -> list[str]:
        return [str(column) for column in self._source.columns]

    @Property(list, notify=columnsChanged)
    def visibleColumns(self) -> list[str]:
        return list(self._visible_columns)

    @Property(list, notify=columnsChanged)
    def filterColumns(self) -> list[str]:
        return ["All columns", *self.allColumns]

    @Property(list, notify=columnsChanged)
    def columnStates(self) -> list[dict[str, object]]:
        visible = set(self._visible_columns)
        return [
            {"name": column, "visible": column in visible}
            for column in self.allColumns
        ]

    @Property(bool, notify=filterChanged)
    def tagFiltersAvailable(self) -> bool:
        return "Style" in self._source.columns or "Theme" in self._source.columns

    @Property(list, notify=filterChanged)
    def styleTagStates(self) -> list[dict[str, object]]:
        return self._tag_states("Style", self._hidden_style_tags)

    @Property(list, notify=filterChanged)
    def themeTagStates(self) -> list[dict[str, object]]:
        return self._tag_states("Theme", self._hidden_theme_tags)

    @Property(int, notify=filterChanged)
    def hiddenTagCount(self) -> int:
        return len(self._hidden_style_tags) + len(self._hidden_theme_tags)

    @Property(bool, notify=filterChanged)
    def isolateTags(self) -> bool:
        return self._isolate_tags

    @Property(bool, notify=filterChanged)
    def kodRangeEnabled(self) -> bool:
        return self._kod_range_enabled

    @Property(float, notify=filterChanged)
    def kodMinimum(self) -> float:
        return self._kod_min

    @Property(float, notify=filterChanged)
    def kodMaximum(self) -> float:
        return self._kod_max

    @Slot(bool, float, float)
    def setKodRange(self, enabled: bool, minimum: float, maximum: float) -> None:
        if not math.isfinite(minimum) or not math.isfinite(maximum):
            return
        self._kod_range_enabled = enabled
        self._kod_min = max(0.0, min(minimum, maximum))
        self._kod_max = max(self._kod_min, max(minimum, maximum))
        self._schedule_tag_update()

    @Property(int, notify=filterChanged)
    def isolatedTagCount(self) -> int:
        return len(self._isolated_tags)

    @Slot(bool)
    def setIsolateTags(self, enabled: bool) -> None:
        self._isolate_tags = enabled
        self._schedule_tag_update()

    @Property(list, notify=columnsChanged)
    def sheetNames(self) -> list[str]:
        return self._sheet_names

    @staticmethod
    def _missing_tempo_mask(frame):
        known = pd.Series(False, index=frame.index)
        for column in frame.columns:
            if str(column).casefold() in {"bpm", "kod"}:
                values = pd.to_numeric(frame[column], errors="coerce")
                known |= values.gt(0) & values.lt(float("inf"))
        return ~known

    @Property(bool, notify=filterChanged)
    def missingTempoOnly(self):
        return self._missing_tempo_only

    @Property(int, notify=summaryChanged)
    def missingTempoCount(self):
        return int(self._missing_tempo_mask(self._source).sum())

    @Slot(bool)
    def setMissingTempoOnly(self, enabled):
        self._missing_tempo_only = enabled
        self._apply_view()

    @Property(str, notify=summaryChanged)
    def summaryText(self) -> str:
        return (
            f"{len(self._view):,} of {len(self._source):,} songs"
            f"  /  {len(self._visible_columns)} of {len(self._source.columns)} columns"
        )

    @Property(str, notify=currentFileChanged)
    def currentFile(self) -> str:
        return self._current_file

    @Property(str, notify=currentFileChanged)
    def currentFileName(self) -> str:
        return Path(self._current_file).name if self._current_file else "No list loaded"

    @Property(str, notify=sortChanged)
    def sortColumn(self) -> str:
        return self._sort_column

    @Property(bool, notify=sortChanged)
    def sortAscending(self) -> bool:
        return self._sort_ascending

    @Property(str, notify=filterChanged)
    def filterColumn(self) -> str:
        return self._filter_column

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter_text

    @Property(str, notify=columnsChanged)
    def styleColumn(self) -> str:
        return self._style_column

    @Property(str, notify=columnsChanged)
    def difficultyColumn(self) -> str:
        return self._difficulty_column

    @Property(list, notify=rolesChanged)
    def legendEntries(self) -> list[dict[str, str]]:
        entries = [
            {"label": "Easy", "color": "#D9EFE2" if not self._dark_theme else "#28513F"},
            {"label": "Medium", "color": "#F5E7BE" if not self._dark_theme else "#5B4925"},
            {"label": "Hard", "color": "#F4D6D2" if not self._dark_theme else "#5C3335"},
        ]
        entries.extend(
            {"label": label, "color": color}
            for label, color in list(self._style_color_map.items())[:8]
        )
        for entry in entries:
            entry["foreground"] = self._foreground_for_fill(entry["color"])
        return entries

    @Slot(int)
    def sortByColumn(self, column: int) -> None:
        if column < 0:
            self.clearSort()
            return
        if not 0 <= column < len(self._visible_columns):
            return
        name = self._visible_columns[column]
        self._sort_ascending = not (
            name == self._sort_column and self._sort_ascending
        )
        self._sort_column = name
        self._apply_view()

    @Slot(str, bool)
    def setSort(self, column: str, ascending: bool) -> None:
        if column not in self._source.columns:
            return
        self._sort_column = column
        self._sort_ascending = ascending
        self._apply_view()

    @Slot()
    def clearSort(self) -> None:
        self._sort_column = ""
        self._sort_ascending = True
        self._apply_view()

    @Slot(str, str, bool)
    def setFilter(self, column: str, text: str, case_sensitive: bool = False) -> None:
        self._filter_column = column if column in self.filterColumns else "All columns"
        self._filter_text = text
        self._case_sensitive = case_sensitive
        self._apply_view()

    @Slot()
    def clearFilter(self) -> None:
        self._filter_column = "All columns"
        self._filter_text = ""
        self._apply_view()

    @Slot(str, str, bool)
    def setTagVisible(self, tag_type: str, tag: str, visible: bool) -> None:
        if self._isolate_tags:
            column = {"style": "Style", "theme": "Theme"}.get(tag_type.casefold())
            if column and tag.strip():
                key = (column, tag.strip().casefold())
                if visible:
                    self._isolated_tags.add(key)
                else:
                    self._isolated_tags.discard(key)
                self._schedule_tag_update()
            return
        hidden = (
            self._hidden_style_tags
            if tag_type.casefold() == "style"
            else self._hidden_theme_tags
            if tag_type.casefold() == "theme"
            else None
        )
        if hidden is None or not tag.strip():
            return
        existing = next(
            (value for value in hidden if value.casefold() == tag.casefold()),
            None,
        )
        if visible and existing is not None:
            hidden.remove(existing)
        elif not visible and existing is None:
            hidden.add(tag.strip())
        self._schedule_tag_update()

    @Slot(str)
    def showAllTags(self, tag_type: str = "") -> None:
        self._isolate_tags = False
        folded = tag_type.casefold()
        if folded in {"", "style"}:
            self._hidden_style_tags.clear()
        if folded in {"", "theme"}:
            self._hidden_theme_tags.clear()
        self._schedule_tag_update()

    @Slot(str, bool)
    def setColumnVisible(self, column: str, visible: bool) -> None:
        if column not in self._source.columns:
            return
        if visible:
            self._hidden_columns.discard(column)
        else:
            self._hidden_columns.add(column)
        self._visible_columns = [
            name for name in self.allColumns if name not in self._hidden_columns
        ]
        self._apply_view()
        self.columnsChanged.emit()

    @Slot()
    def showAllColumns(self) -> None:
        self._hidden_columns.clear()
        self._visible_columns = self.allColumns
        self._apply_view()
        self.columnsChanged.emit()

    @Slot(str, str)
    def setSemanticColumns(self, style_column: str, difficulty_column: str) -> None:
        self._style_column = style_column if style_column in self._source.columns else ""
        self._difficulty_column = (
            difficulty_column if difficulty_column in self._source.columns else ""
        )
        self._apply_view()
        self.columnsChanged.emit()

    @Slot(bool, bool, bool)
    def setColorOptions(
        self,
        color_styles: bool,
        color_difficulty: bool,
        highlight_blanks: bool,
    ) -> None:
        self._color_styles = color_styles
        self._color_difficulty = color_difficulty
        self._highlight_blanks = highlight_blanks
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [BACKGROUND_ROLE, FOREGROUND_ROLE],
            )

    @Slot(bool)
    def setDarkTheme(self, enabled: bool) -> None:
        self._dark_theme = enabled
        self._refresh_color_metadata()
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [BACKGROUND_ROLE, FOREGROUND_ROLE],
            )
        self.rolesChanged.emit()

    @Slot(int, result=int)
    def preferredColumnWidth(self, column: int) -> int:
        if not 0 <= column < len(self._visible_columns):
            return 120
        name = self._visible_columns[column]
        sample = self._view[name].head(150).map(self._display_value)
        longest = max([len(name), *(len(value) for value in sample)], default=len(name))
        return max(110, min(310, longest * 8 + 34))

    @Slot(str, result="QVariantList")
    def tagChoices(self, column):
        return self._allowed_tags.get(column.casefold(), [])

    @Slot(str, str, result="QVariantMap")
    def validateTagEdit(self, column, text):
        allowed = {tag.casefold(): tag for tag in self.tagChoices(column)}
        selected = []
        for tag in self._split_tags(text):
            canonical = allowed.get(tag.casefold())
            if canonical is None:
                return {"valid": False, "value": "", "error": f"Choose a predefined {column} tag: {tag}"}
            if canonical not in selected:
                selected.append(canonical)
        return {"valid": True, "value": "; ".join(selected), "error": ""}

    @Slot(int, int, result="QVariantMap")
    def tagEditContext(self, row, column):
        if not 0 <= row < len(self._view) or not 0 <= column < len(self._visible_columns):
            return {}
        index = self._view.index[row]
        name = self._visible_columns[column]
        return {"key": self._row_keys[index], "column": name, "value": str(self._source.at[index, name]) if not self._is_blank(self._source.at[index, name]) else ""}

    @Slot("QVariantMap", str, result=bool)
    def saveTagEdit(self, context, text):
        column = context.get("column")
        if column not in self._visible_columns:
            return False
        result = self.validateTagEdit(column, text)
        if not result["valid"]:
            return False
        # Locate the original song even if sorting/filtering changed while editing.
        for row, index in enumerate(self._view.index):
            if self._row_keys[index] == context.get("key"):
                return self.editCell(row, self._visible_columns.index(column), result["value"])
        return False

    @Slot(int, int, result="QVariantMap")
    def fieldResetPreview(self, row, column):
        if not 0 <= row < len(self._view) or not 0 <= column < len(self._visible_columns):
            return {}
        index = self._view.index[row]
        key = self._row_keys[index]
        name = self._visible_columns[column]
        if not self.data(self.index(row, column), EDITED_ROLE):
            return {}
        original = self._field_data["originals"].get(key, {})
        return {"key": key, "column": name, "current": self._display_value(self._source.at[index, name]),
                "original": self._display_value(original.get(name, "")), "linked": name.casefold() in {"bpm", "kod"}}

    @Slot("QVariantMap", result=bool)
    def resetField(self, request):
        key, column = request.get("key"), request.get("column")
        if not key or not column:
            return False
        try:
            original = field_store.load()["originals"].get(key)
            if original is None:
                return False
            matching = [index for index, identity in self._row_keys.items() if identity == key]
            if not matching or column not in self._source:
                return False
            if request.get("original") != self._display_value(original.get(column, "")) or request.get("current") != self._display_value(self._source.at[matching[0], column]):
                return False
            columns = [column]
            if column.casefold() in {"bpm", "kod"}:
                columns = ["BPM", "KOD"]
                data = tempo_store.load()
                for index, identity in self._row_keys.items():
                    if identity == key:
                        data["corrections"].pop(tempo_store.key(tempo_store.song(self._source.loc[index].to_dict())), None)
                tempo_store.save(data)
            field_store.reset(key, columns)
            frame = self._source.copy()
            for index, identity in self._row_keys.items():
                if identity == key:
                    for name in columns:
                        if name in frame:
                            frame[name] = frame[name].astype(object)
                            frame.at[index, name] = original.get(name, "")
            self.set_frame(frame, self.currentFile, self.sheetNames, remember_originals=False)
            return True
        except (OSError, ValueError):
            return False

    @Slot(int, int, str, result=bool)
    def editCell(self, row: int, column: int, value: str) -> bool:
        return self.setData(self.index(row, column), value, Qt.ItemDataRole.EditRole)

    @Slot(int, result="QVariantMap")
    def rowRecord(self, row: int) -> dict[str, object]:
        if not 0 <= row < len(self._view):
            return {}
        record = self._source.loc[self._view.index[row]].to_dict()
        return {
            str(column): "" if self._is_blank(value) else self._display_value(value)
            for column, value in record.items()
        }

    def export_view(
        self,
        output_path: str,
        csv_delimiter: str = ",",
        text_encoding: str = "utf-8-sig",
    ) -> Path:
        return write_table_file(
            self._view.reset_index(drop=True),
            output_path,
            csv_delimiter=csv_delimiter,
            text_encoding=text_encoding,
            sheet_name="Songs",
        )

    def settings_snapshot(self) -> dict[str, object]:
        return {
            "viewer_file": self._current_file,
            "viewer_style_column": self._style_column,
            "viewer_difficulty_column": self._difficulty_column,
            "viewer_hidden_columns": sorted(self._hidden_columns),
            "viewer_filter_column": self._filter_column,
            "viewer_filter_text": self._filter_text,
            "viewer_sort_column": self._sort_column,
            "viewer_sort_ascending": self._sort_ascending,
            "viewer_color_styles": self._color_styles,
            "viewer_color_difficulty": self._color_difficulty,
            "viewer_highlight_blanks": self._highlight_blanks,
            "viewer_isolate_tags": self._isolate_tags,
            "viewer_kod_range_enabled": self._kod_range_enabled,
            "viewer_kod_minimum": self._kod_min,
            "viewer_kod_maximum": self._kod_max,
            "viewer_isolated_tags": [list(tag) for tag in sorted(self._isolated_tags)],
            "viewer_hidden_styles": sorted(self._hidden_style_tags),
            "viewer_hidden_themes": sorted(self._hidden_theme_tags),
        }

    def restore_settings(self, settings: dict[str, object]) -> None:
        self._kod_range_enabled = bool(settings.get("viewer_kod_range_enabled", False))
        self._kod_min = float(settings.get("viewer_kod_minimum", 0))
        self._kod_max = float(settings.get("viewer_kod_maximum", 200))
        hidden = settings.get("viewer_hidden_columns", [])
        self._hidden_columns = (
            {str(value) for value in hidden} if isinstance(hidden, list) else set()
        )
        self._style_column = str(settings.get("viewer_style_column", ""))
        self._difficulty_column = str(settings.get("viewer_difficulty_column", ""))
        self._filter_column = str(settings.get("viewer_filter_column", "All columns"))
        self._filter_text = str(settings.get("viewer_filter_text", ""))
        self._sort_column = str(settings.get("viewer_sort_column", ""))
        self._sort_ascending = bool(settings.get("viewer_sort_ascending", True))
        self._color_styles = bool(settings.get("viewer_color_styles", True))
        self._color_difficulty = bool(settings.get("viewer_color_difficulty", True))
        self._highlight_blanks = bool(settings.get("viewer_highlight_blanks", False))
        self._isolate_tags = bool(settings.get("viewer_isolate_tags", False))
        self._isolated_tags = {tuple(tag) for tag in settings.get("viewer_isolated_tags", [])
                               if isinstance(tag, (list, tuple)) and len(tag) == 2}
        hidden_styles = settings.get("viewer_hidden_styles", [])
        self._hidden_style_tags = (
            {str(value) for value in hidden_styles}
            if isinstance(hidden_styles, list)
            else set()
        )
        hidden_themes = settings.get("viewer_hidden_themes", [])
        self._hidden_theme_tags = (
            {str(value) for value in hidden_themes}
            if isinstance(hidden_themes, list)
            else set()
        )
