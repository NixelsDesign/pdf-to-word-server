"""
PDF -> Word converter server (with OCR for scanned PDFs).

Run locally:   uvicorn main:app --reload
Then open:     http://localhost:8000
"""

import os
import shutil
import tempfile
import threading
from pathlib import Path

try:
    import pymupdf as fitz  # newer PyMuPDF name
except ImportError:
    import fitz

import ocrmypdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pdf2docx import Converter
from starlette.background import BackgroundTask

# ---- Limits (keep these small on a free host so it doesn't crash) ----
MAX_MB = int(os.getenv("MAX_MB", "15"))        # biggest upload allowed
MAX_PAGES = int(os.getenv("MAX_PAGES", "20"))  # most pages allowed
OCR_LANG = os.getenv("OCR_LANG", "eng")        # OCR language(s), e.g. "eng+fra"

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(title="PDF to Word")

# Lets the phone app (built later) call this server. Fine for learning;
# tighten allow_origins if you ever make this public for real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Used-OCR"],
)

# Only one conversion at a time: free hosts have very little memory.
busy = threading.Semaphore(1)


def needs_ocr(doc) -> bool:
    """True if at least half the pages have (almost) no real text = a scan."""
    empty = sum(1 for page in doc if len(page.get_text().strip()) < 20)
    return empty * 2 >= len(doc)


def make_visible_text_pdf(ocr_pdf: Path, out_pdf: Path) -> None:
    """
    OCR adds the text as an *invisible* layer on top of the scan image, and
    pdf2docx ignores invisible text (you would just get the picture in Word).
    So we rebuild each page with the recognised text drawn visibly, which
    gives pdf2docx real, editable text to work with.
    """
    src = fitz.open(ocr_pdf)
    new = fitz.open()
    for page in src:
        out_page = new.new_page(width=page.rect.width, height=page.rect.height)
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    if not text.strip():
                        continue
                    size = max(span["size"], 6)
                    width = span["bbox"][2] - span["bbox"][0]
                    natural = fitz.get_text_length(text, fontname="helv", fontsize=size)
                    if natural > width > 0:
                        size = max(size * width / natural, 4)
                    try:
                        out_page.insert_text(span["origin"], text, fontname="helv", fontsize=size)
                    except Exception:
                        pass  # skip characters the basic font can't draw
    new.save(out_pdf)
    new.close()
    src.close()


@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/convert")
def convert(file: UploadFile = File(...)):
    name = file.filename or "document.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file.")

    work = Path(tempfile.mkdtemp(prefix="p2w_"))
    try:
        # 1. Save the upload, enforcing the size limit
        src = work / "input.pdf"
        size = 0
        with open(src, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_MB * 1024 * 1024:
                    raise HTTPException(413, f"File too large (max {MAX_MB} MB).")
                out.write(chunk)

        # 2. Check it's a real, readable PDF within the page limit
        try:
            doc = fitz.open(src)
        except Exception:
            raise HTTPException(400, "That doesn't look like a valid PDF.")
        if doc.needs_pass:
            raise HTTPException(400, "This PDF is password-protected.")
        if len(doc) > MAX_PAGES:
            raise HTTPException(413, f"Too many pages (max {MAX_PAGES}).")
        scanned = needs_ocr(doc)
        doc.close()

        # 3. Convert (one job at a time)
        if not busy.acquire(timeout=120):
            raise HTTPException(503, "Server is busy, please try again shortly.")
        try:
            pdf_for_word = src
            if scanned:
                ocr_pdf = work / "ocr.pdf"
                try:
                    ocrmypdf.ocr(
                        src, ocr_pdf,
                        language=OCR_LANG,
                        skip_text=True,   # leave pages that already have text alone
                        deskew=True,      # straighten slightly tilted scans
                        optimize=0,
                        jobs=1,
                        progress_bar=False,
                    )
                except Exception as exc:
                    raise HTTPException(500, f"OCR failed: {exc}")
                try:
                    pdf_for_word = work / "text.pdf"
                    make_visible_text_pdf(ocr_pdf, pdf_for_word)
                except Exception as exc:
                    raise HTTPException(500, f"Could not process OCR text: {exc}")

            docx = work / "output.docx"
            cv = Converter(str(pdf_for_word))
            try:
                cv.convert(str(docx))
            except Exception as exc:
                raise HTTPException(500, f"Conversion failed: {exc}")
            finally:
                cv.close()
        finally:
            busy.release()

        # 4. Send the Word file back, then delete the temp folder
        return FileResponse(
            docx,
            media_type=DOCX_TYPE,
            filename=Path(name).stem + ".docx",
            headers={"X-Used-OCR": "true" if scanned else "false"},
            background=BackgroundTask(shutil.rmtree, work, ignore_errors=True),
        )
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
