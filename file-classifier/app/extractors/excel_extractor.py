import io
import pandas as pd
import structlog
from app.extractors.base import BaseExtractor, ExtractionResult

logger = structlog.get_logger()

MAX_ROWS = 50
MAX_COLS = 30


class ExcelExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        logger.info("Extracting Excel content", filename=filename)
        buf = io.BytesIO(file_bytes)

        try:
            xls = pd.ExcelFile(buf, engine="openpyxl")
        except Exception:
            xls = pd.ExcelFile(buf, engine="xlrd")

        sheet_names = xls.sheet_names
        parts = []
        total_rows = 0

        for sheet in sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet, nrows=MAX_ROWS)
            df = df.iloc[:, :MAX_COLS]
            total_rows += len(df)

            parts.append(f"### Sheet: {sheet}")
            parts.append(f"Columns: {', '.join(str(c) for c in df.columns.tolist())}")
            parts.append(df.to_markdown(index=False))
            parts.append("")

        text = "\n".join(parts)

        return ExtractionResult(
            text_content=text,
            metadata={
                "sheet_names": sheet_names,
                "total_sheets": len(sheet_names),
                "sample_rows": total_rows,
            },
        )


class CsvExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        logger.info("Extracting CSV content", filename=filename)
        buf = io.BytesIO(file_bytes)
        df = pd.read_csv(buf, nrows=MAX_ROWS)
        df = df.iloc[:, :MAX_COLS]

        text = f"Columns: {', '.join(str(c) for c in df.columns.tolist())}\n\n"
        text += df.to_markdown(index=False)

        return ExtractionResult(
            text_content=text,
            metadata={"total_columns": len(df.columns), "sample_rows": len(df)},
        )
