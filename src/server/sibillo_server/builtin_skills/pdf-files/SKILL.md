---
name: pdf-files
description: Use to read, split, merge, fill or inspect PDF files, to look at their pages as images, and to make new PDFs from Markdown, Word files or Typst documents.
---

# PDF files

Everything here is in the sandbox already; install nothing.

## Read a PDF

- Text, keeping the layout of columns and tables: `pdftotext -layout in.pdf -` (or a file instead of `-`).
- One page or a range: `pdftotext -f 3 -l 5 -layout in.pdf -`.
- Markdown, with headings and tables where the PDF has them: `markitdown in.pdf`.
- Pages, metadata, page size and whether it is encrypted: `pdfinfo in.pdf`.
- A scanned PDF has no text: `pdftotext` prints nothing. There is no text recognition in the
  sandbox; tell the user, or turn the pages into images if you can look at images.

## Pages as images

`pdftoppm -png -r 110 -f 1 -l 1 in.pdf /scratch/page` writes `/scratch/page-1.png`. Use `-jpeg`
for smaller files, and a higher `-r` for small print.

## Split, merge, rotate, decrypt

qpdf changes PDFs without rendering them again:

```sh
qpdf --empty --pages a.pdf b.pdf -- merged.pdf          # merge
qpdf in.pdf --pages . 1-3 -- first-three.pdf            # keep pages 1 to 3
qpdf in.pdf --rotate=+90:2 rotated.pdf                  # rotate page 2
qpdf --decrypt --password=SECRET in.pdf plain.pdf       # remove a password the user gave you
```

For form fields and page-level edits from Python, use pypdf:

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("form.pdf")
print(reader.get_fields())  # the form's fields and their values
writer = PdfWriter(clone_from=reader)
writer.update_page_form_field_values(writer.pages[0], {"name": "Ada"}, auto_regenerate=False)
writer.write("filled.pdf")
```

## Make a PDF

Write Markdown and convert it with pandoc and Typst, which needs no other options:

```sh
pandoc report.md -o report.pdf --pdf-engine=typst
pandoc letter.docx -o letter.pdf --pdf-engine=typst      # a Word file, without its exact layout
```

For control over the layout, write a Typst document and compile it with `typst compile doc.typ`.
The fonts are DejaVu, Liberation (metric-compatible with Arial, Times New Roman and Courier New)
and Noto; name one with `#set text(font: "Liberation Sans")`.

There is no office suite: a Word or PowerPoint file cannot be turned into a PDF with its exact
layout. Say so when it matters.
