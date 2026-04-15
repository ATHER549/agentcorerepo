from app.extractors.base import BaseExtractor
from app.extractors.excel_extractor import ExcelExtractor, CsvExtractor
from app.extractors.pdf_extractor import PdfExtractor
from app.extractors.word_extractor import WordExtractor
from app.extractors.text_extractor import TextExtractor
from app.extractors.image_extractor import ImageExtractor

_EXTRACTORS: dict[str, BaseExtractor] = {
    "excel": ExcelExtractor(),
    "csv": CsvExtractor(),
    "pdf": PdfExtractor(),
    "word": WordExtractor(),
    "text": TextExtractor(),
    "image": ImageExtractor(),
}


def get_extractor(file_type: str) -> BaseExtractor:
    extractor = _EXTRACTORS.get(file_type)
    if not extractor:
        raise ValueError(f"No extractor found for file type: {file_type}")
    return extractor
