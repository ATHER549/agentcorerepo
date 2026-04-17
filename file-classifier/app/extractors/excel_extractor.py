import io
import pandas as pd
import structlog
from app.extractors.base import BaseExtractor, ExtractionResult

logger = structlog.get_logger()

MAX_ROWS_PER_SHEET = 40
MAX_COLS = 30
MAX_SHEETS_DETAILED = 8  # extract full content for first N sheets; summarize the rest


def _open_excel_file(buf: io.BytesIO) -> pd.ExcelFile:
    """Try openpyxl first, fall back to xlrd. Handles .xls files that are actually xlsx internally."""
    for engine in ("openpyxl", "xlrd"):
        try:
            buf.seek(0)
            return pd.ExcelFile(buf, engine=engine)
        except Exception:
            continue
    raise ValueError("Failed to open Excel file with both openpyxl and xlrd engines")


class ExcelExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        logger.info("Extracting Excel content", filename=filename)
        buf = io.BytesIO(file_bytes)

        xls = _open_excel_file(buf)

        sheet_names = xls.sheet_names
        parts = []
        total_rows = 0

        # Header summary — gives the LLM a quick bird's-eye view (critical for MPBC detection)
        parts.append(f"## Workbook Structure")
        parts.append(f"Total Sheets: {len(sheet_names)}")
        parts.append(f"Sheet Names: {sheet_names}")
        parts.append("")

        for idx, sheet in enumerate(sheet_names):
            try:
                # Read with no header first to capture top rows that may contain title/metadata
                df_raw = pd.read_excel(xls, sheet_name=sheet, nrows=MAX_ROWS_PER_SHEET, header=None)
                df_raw = df_raw.iloc[:, :MAX_COLS]
            except Exception as e:
                parts.append(f"### Sheet: {sheet} (failed to read: {e})")
                continue

            non_empty_rows = df_raw.dropna(how="all").shape[0]
            total_rows += non_empty_rows

            if idx < MAX_SHEETS_DETAILED:
                parts.append(f"### Sheet {idx + 1}: '{sheet}'")
                parts.append(f"Non-empty rows in sample: {non_empty_rows}")

                # Render as markdown — preserves table structure for the LLM
                try:
                    md = df_raw.fillna("").astype(str).to_markdown(index=False, headers=[
                        f"col_{c}" for c in range(df_raw.shape[1])
                    ])
                    parts.append(md)
                except Exception:
                    parts.append(df_raw.fillna("").astype(str).to_string(index=False))
                parts.append("")
            else:
                parts.append(f"### Sheet {idx + 1}: '{sheet}' (summary only — {non_empty_rows} non-empty rows)")
                parts.append("")

        text = "\n".join(parts)

        return ExtractionResult(
            text_content=text,
            metadata={
                "sheet_names": sheet_names,
                "total_sheets": len(sheet_names),
                "sample_rows": total_rows,
                "multi_sheet": len(sheet_names) > 1,
            },
        )


class CsvExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        logger.info("Extracting CSV content", filename=filename)
        buf = io.BytesIO(file_bytes)
        df = pd.read_csv(buf, nrows=MAX_ROWS_PER_SHEET, header=None)
        df = df.iloc[:, :MAX_COLS]

        text = "## CSV Content\n\n"
        try:
            text += df.fillna("").astype(str).to_markdown(index=False, headers=[
                f"col_{c}" for c in range(df.shape[1])
            ])
        except Exception:
            text += df.fillna("").astype(str).to_string(index=False)

        return ExtractionResult(
            text_content=text,
            metadata={"total_columns": len(df.columns), "sample_rows": len(df)},
        )
