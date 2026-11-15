---
name: office-files
description: Use to read, change or make Word documents (.docx), Excel workbooks (.xlsx) and PowerPoint presentations (.pptx), and to turn them into Markdown, PDF or other formats.
---

# Office files

The sandbox's python3 has python-docx, openpyxl and python-pptx, and markitdown; there is no office
suite. Install nothing.

## Read one

`markitdown file.docx` (or `.xlsx`, `.pptx`, `.html`) prints Markdown: the quickest way to read a
document's text and tables. For cell values, formulas or a slide's shapes, use the libraries below.

## Word documents: python-docx

```python
from docx import Document

document = Document("in.docx")
for paragraph in document.paragraphs:
    print(paragraph.style.name, paragraph.text)
document.add_heading("Summary", level=1)
document.add_paragraph("Written by the assistant.")
document.save("/workspace/out.docx")
```

Changing text inside a paragraph keeps its formatting only if you change the text of its runs
(`paragraph.runs`), not `paragraph.text`.

## Excel workbooks: openpyxl

```python
from openpyxl import load_workbook

book = load_workbook("in.xlsx")  # formulas as written
values = load_workbook("in.xlsx", data_only=True)  # the values Excel last computed
sheet = book.active
sheet["B2"] = 42
sheet["B3"] = "=SUM(B1:B2)"  # computed when the user opens it
book.save("/workspace/out.xlsx")
```

openpyxl does not compute formulas. For analysis, read the sheet with pandas:
`pandas.read_excel("in.xlsx", sheet_name=None)` gives every sheet as a table.

## PowerPoint presentations: python-pptx

```python
from pptx import Presentation
from pptx.util import Inches

deck = Presentation()
slide = deck.slides.add_slide(deck.slide_layouts[1])
slide.shapes.title.text = "Quarterly budget"
slide.placeholders[1].text = "Spending is 4% under plan"
slide.shapes.add_picture("/scratch/chart.png", Inches(1), Inches(3), width=Inches(6))
deck.save("/workspace/budget.pptx")
```

## Convert

pandoc converts between Word, Markdown, HTML and others, and makes PDFs with Typst:

```sh
pandoc in.docx -o out.md
pandoc notes.md -o notes.docx
pandoc notes.md -o notes.pdf --pdf-engine=typst
```

Layout does not survive conversion exactly. Spreadsheets and presentations convert only through
markitdown, as Markdown.
