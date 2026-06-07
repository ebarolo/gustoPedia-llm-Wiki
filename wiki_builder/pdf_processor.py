import logging
import os
from typing import List, Optional, Tuple
import pymupdf
import pymupdf4llm

logger = logging.getLogger(__name__)

class PDFProcessor:
    @staticmethod
    def extract_markdown(
        pdf_path: str,
        pages: Optional[List[int]] = None,
        exclude_header_footer: bool = True
    ) -> str:
        """
        Converts a PDF file to a structured Markdown string using PyMuPDF4LLM.

        Args:
            pdf_path: Path to the PDF file on disk.
            pages: List of 0-based page numbers to extract. If None, extracts the entire document.
            exclude_header_footer: If True, repetitive page headers and footers are omitted.

        Returns:
            The converted Markdown string.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            logger.info("Extracting markdown from %s, pages=%s", pdf_path, pages)
            
            # Use PyMuPDF4LLM to convert to Markdown
            markdown_content = pymupdf4llm.to_markdown(
                pdf_path,
                pages=pages,
                header=not exclude_header_footer,
                footer=not exclude_header_footer
            )
            return markdown_content
        except Exception as e:
            logger.exception("Failed to convert PDF to Markdown for %s", pdf_path)
            raise RuntimeError(f"Error during PDF to Markdown conversion: {str(e)}") from e

    @staticmethod
    def get_toc_and_page_count(pdf_path: str) -> Tuple[List[List], int]:
        """
        Extracts the Table of Contents (TOC) and total page count of a PDF using PyMuPDF.

        Args:
            pdf_path: Path to the PDF file on disk.

        Returns:
            A tuple of (TOC list, total_page_count).
            The TOC list format is: [[level, title, page_number], ...]
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            doc = pymupdf.open(pdf_path)
            toc = doc.get_toc()
            page_count = doc.page_count
            doc.close()
            return toc, page_count
        except Exception as e:
            logger.exception("Failed to get TOC/metadata for %s", pdf_path)
            raise RuntimeError(f"Error reading PDF metadata: {str(e)}") from e
