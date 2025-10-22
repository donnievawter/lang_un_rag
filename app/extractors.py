"""
Local document extractors for lang_un_rag.

Each extractor returns a list of dicts: {"text": str, "metadata": {...}}

Supports:
- PDF (born-digital via pdfplumber/pypdf; fallback to OCR if very little text)
- DOCX
- PPTX
- HTML
- Images (OCR via Tesseract)
- CSV
- Plain text fallback
"""
import os
import mimetypes
from typing import List, Dict

try:
    import magic  # python-magic
except Exception:
    magic = None

# PDF
import pdfplumber
from pypdf import PdfReader

# DOCX
import docx

# PPTX
from pptx import Presentation

# HTML
from bs4 import BeautifulSoup

# Images / OCR
from PIL import Image
import pytesseract
from pdf2image import convert_from_path

# CSV/Excel
import pandas as pd

# Heuristic thresholds
MIN_PDF_TEXT_LEN = 200  # if extracted text shorter than this, consider OCR fallback

def detect_mime(path: str) -> str:
    if magic:
        try:
            return magic.from_file(path, mime=True)
        except Exception:
            pass
    return mimetypes.guess_type(path)[0] or "application/octet-stream"

def extract_from_pdf(path: str) -> List[Dict]:
    texts = []
    try:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                text = text.strip()
                if text:
                    texts.append({"text": text, "metadata": {"file": os.path.basename(path), "page": i + 1, "file_type": "pdf"}})
    except Exception:
        # fallback to pypdf
        try:
            reader = PdfReader(path)
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                text = text.strip()
                if text:
                    texts.append({"text": text, "metadata": {"file": os.path.basename(path), "page": i + 1, "file_type": "pdf"}})
        except Exception:
            pass

    # If we got very little text overall, treat as scanned and OCR
    total_chars = sum(len(p["text"]) for p in texts)
    if total_chars < MIN_PDF_TEXT_LEN:
        return extract_from_scanned_pdf(path)
    return texts

def extract_from_scanned_pdf(path: str) -> List[Dict]:
    out = []
    try:
        pages = convert_from_path(path, dpi=200)  # requires poppler
        for i, page in enumerate(pages):
            text = pytesseract.image_to_string(page)
            text = text.strip()
            if text:
                out.append({"text": text, "metadata": {"file": os.path.basename(path), "page": i + 1, "file_type": "scanned_pdf"}})
    except Exception:
        pass
    return out

def extract_from_docx(path: str) -> List[Dict]:
    out = []
    try:
        doc = docx.Document(path)
        para_texts = []
        for para in doc.paragraphs:
            t = para.text.strip()
            if t:
                para_texts.append(t)
        # Group paragraphs into larger pieces to avoid tiny chunks
        if para_texts:
            out.append({"text": "\n\n".join(para_texts), "metadata": {"file": os.path.basename(path), "file_type": "docx"}})
    except Exception:
        pass
    return out

def extract_from_pptx(path: str) -> List[Dict]:
    out = []
    try:
        prs = Presentation(path)
        for s_idx, slide in enumerate(prs.slides):
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    slide_text.append(shape.text.strip())
            if slide_text:
                out.append({"text": "\n".join(slide_text), "metadata": {"file": os.path.basename(path), "slide": s_idx + 1, "file_type": "pptx"}})
    except Exception:
        pass
    return out

def extract_from_html(path: str) -> List[Dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            markup = f.read()
        soup = BeautifulSoup(markup, "html.parser")
        parts = []
        for el in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            txt = el.get_text(separator=" ", strip=True)
            if txt:
                parts.append(txt)
        if parts:
            out.append({"text": "\n\n".join(parts), "metadata": {"file": os.path.basename(path), "file_type": "html"}})
    except Exception:
        pass
    return out

def extract_from_image(path: str) -> List[Dict]:
    out = []
    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        text = text.strip()
        if text:
            out.append({"text": text, "metadata": {"file": os.path.basename(path), "file_type": "image"}})
    except Exception:
        pass
    return out

def extract_from_csv(path: str) -> List[Dict]:
    out = []
    try:
        df = pd.read_csv(path)
        rows = []
        for i, row in df.iterrows():
            parts = [f"{col}: {row[col]}" for col in df.columns]
            rows.append("; ".join(parts))
        if rows:
            out.append({"text": "\n".join(rows), "metadata": {"file": os.path.basename(path), "file_type": "csv"}})
    except Exception:
        pass
    return out

def extract_fallback_text(path: str) -> List[Dict]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()
        if text:
            return [{"text": text, "metadata": {"file": os.path.basename(path), "file_type": "text"}}]
    except Exception:
        pass
    return []

def extract(path: str) -> List[Dict]:
    mime = detect_mime(path) or ""
    lower = path.lower()
    try:
        if lower.endswith(".pdf") or (mime and mime.startswith("application/pdf")):
            return extract_from_pdf(path)
        if lower.endswith(".docx"):
            return extract_from_docx(path)
        if lower.endswith(".pptx"):
            return extract_from_pptx(path)
        if lower.endswith(".html") or lower.endswith(".htm") or mime == "text/html":
            return extract_from_html(path)
        if lower.endswith(".csv"):
            return extract_from_csv(path)
        if lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif")) or (mime and mime.startswith("image/")):
            return extract_from_image(path)
        # fallback: try plain text
        return extract_fallback_text(path)
    except Exception:
        return []