# PDF Coordinates Extractor (GitHub to Render Deployment)

Full-stack Python FastAPI backend + HTML/JS frontend for high-precision PDF coordinate and schedule extraction.

## Deployment Steps

1. Create a GitHub Repository and push these files.
2. Sign in to [Render.com](https://render.com).
3. Click **New +** -> **Web Service** (or **Blueprint**).
4. Connect your GitHub repository.
5. Render will automatically build using `requirements.txt` and start the server using `main.py`.

## OCR Support (scanned / image-only PDFs)

Pages with no extractable text layer are automatically retried using OCR. This relies on the
system Tesseract-OCR engine, not just a Python package, so:

- **Render:** `render.yaml` installs `tesseract-ocr` via `apt-get` during the build and sets
  `TESSDATA_PREFIX`. If your Render plan/image blocks `apt-get` in `buildCommand`, switch to a
  Docker-based Render service with a Dockerfile that installs `tesseract-ocr`.
- **Local dev:** install it with `sudo apt-get install tesseract-ocr` (Debian/Ubuntu) or the
  equivalent for your OS, then restart `uvicorn`.
- OCR can be disabled per request by sending `enable_ocr=false` in the upload form (the frontend
  exposes this as a checkbox). If OCR is requested but Tesseract isn't installed, the API still
  responds normally with `used_ocr: false` and an `ocr_error` message on the affected page instead
  of failing the request.

