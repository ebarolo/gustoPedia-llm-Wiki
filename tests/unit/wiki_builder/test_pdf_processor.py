import os
import tempfile
import pytest
import pymupdf
from wiki_builder.pdf_processor import PDFProcessor

@pytest.fixture
def temp_pdf_file():
    # Create a simple PDF using pymupdf
    doc = pymupdf.open()
    
    def draw_text(page, text, y_start=150):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            page.insert_text((50, y_start + i * 20), line)
            
    # Page 1: Chapter 1 / TOC
    page1 = doc.new_page()
    draw_text(page1, "Table of Contents\nChapter 1: Appetizers... page 2\nChapter 2: Main Courses... page 3")
    
    # Page 2: Chapter 1 content
    page2 = doc.new_page()
    draw_text(page2, "Recipe: Tomato Bruschetta\nIngredients: tomatoes, garlic, basil, olive oil, bread.")
    
    # Page 3: Chapter 2 content
    page3 = doc.new_page()
    draw_text(page3, "Recipe: Classic Lasagna\nIngredients: pasta, bolognese, bechamel, parmesan.")
    
    # Set TOC
    toc = [
        [1, "Table of Contents", 1],
        [1, "Chapter 1", 2],
        [1, "Chapter 2", 3],
    ]
    doc.set_toc(toc)
    
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    temp_path = tmp.name
    tmp.close()
    
    doc.save(temp_path)
    doc.close()
    
    yield temp_path
    
    if os.path.exists(temp_path):
        os.remove(temp_path)

def test_extract_markdown_entire_doc(temp_pdf_file):
    markdown = PDFProcessor.extract_markdown(temp_pdf_file)
    assert "Tomato Bruschetta" in markdown
    assert "Classic Lasagna" in markdown

def test_extract_markdown_specific_pages(temp_pdf_file):
    # Extract only page 2 (0-indexed is page 1)
    markdown = PDFProcessor.extract_markdown(temp_pdf_file, pages=[1])
    assert "Tomato Bruschetta" in markdown
    assert "Classic Lasagna" not in markdown

def test_get_toc_and_page_count(temp_pdf_file):
    toc, page_count = PDFProcessor.get_toc_and_page_count(temp_pdf_file)
    assert page_count == 3
    assert len(toc) == 3
    # TOC contains: [level, title, page_number]
    assert toc[0][1] == "Table of Contents"
    assert toc[1][1] == "Chapter 1"
    assert toc[2][1] == "Chapter 2"
    assert toc[1][2] == 2

def test_pdf_not_found():
    with pytest.raises(FileNotFoundError):
        PDFProcessor.extract_markdown("non_existent_file.pdf")
        
    with pytest.raises(FileNotFoundError):
        PDFProcessor.get_toc_and_page_count("non_existent_file.pdf")
