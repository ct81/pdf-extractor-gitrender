# PDF Coordinates Extractor (GitHub to Render Deployment)

Full-stack Python FastAPI backend + HTML/JS frontend for high-precision PDF coordinate and schedule extraction.

## Deployment Steps

1. Create a GitHub Repository and push these files (including the `Dockerfile`).
2. Sign in to [Render.com](https://render.com).
3. Click **New +** -> **Blueprint** (recommended, reads `render.yaml`) or **Web Service**.
4. Connect your GitHub repository.
5. Render builds and runs the service from the `Dockerfile` (`env: docker` in `render.yaml`),
   which installs Tesseract as part of the image build and starts `main.py` via `uvicorn`.

   If you create the Web Service manually instead of via Blueprint, set its **Environment** to
   **Docker** so Render uses the `Dockerfile` instead of the native Python buildpack.

## OCR Support (scanned / image-only PDFs, or CAD text drawn as vector paths)

Pages are rasterized to an image with PyMuPDF and read with `pytesseract` (shells out to the
system `tesseract` binary), because CAD schedules often draw text as vector paths that have no
real text layer at all, so PyMuPDF's normal text extraction returns nothing for those labels.

- **When it runs:** automatically for any page with no extractable text layer, or on every page
  if you enable "Always OCR (ignore embedded text)" in the frontend (`force_ocr=true`), which is
  the option to use for drawings where the schedule grid itself has no real text objects.
- **Render:** deployment must use the **Docker** environment (see Deployment Steps above), which
  builds from the `Dockerfile` and installs `tesseract-ocr` as root. Render's native `env: python`
  buildpack runs `buildCommand` as a non-root user, so `apt-get install` silently fails there and
  the API responds with `used_ocr: false` / `ocr_error: "tesseract is not installed..."`.
- **Local dev:** install it with `sudo apt-get install tesseract-ocr` (Debian/Ubuntu) or the
  equivalent for your OS, then restart `uvicorn`.
- OCR can be disabled entirely by sending `enable_ocr=false`. If OCR is requested but Tesseract
  isn't installed, the API still responds normally with `used_ocr: false` and an `ocr_error`
  message on the affected page instead of failing the request.

## Optional Page Layout Analysis

The **PyMuPDF layout analysis** checkbox runs `pymupdf-layout` on pages with a native text layer.
It returns labeled region bounding boxes in the `layout_regions` response field, the on-screen
Page Layout Regions table, and the `Layout_Regions` Excel sheet. The option is off by default;
loading the model used about 106 MB of additional resident memory in local testing. OCR-only
pages are skipped because the analyzer reads PDF-native content, not the text recognized by
Tesseract. Use it for text-rich PDFs where improved reading-order and region classification are
useful, not as an OCR enhancement for scanned/vector-outline drawings.


