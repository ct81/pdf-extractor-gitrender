# PDF Coordinates Extractor (GitHub to Render Deployment)

Full-stack Python FastAPI backend + HTML/JS frontend for high-precision PDF coordinate and schedule extraction.

## Deployment Steps

1. Create a GitHub Repository and push these files.
2. Sign in to [Render.com](https://render.com).
3. Click **New +** -> **Web Service** (or **Blueprint**).
4. Connect your GitHub repository.
5. Render will automatically build using `requirements.txt` and start the server using `main.py`.

## OCR Support (scanned / image-only PDFs, or CAD text drawn as vector paths)

Pages are rasterized to an image with PyMuPDF and read with `pytesseract` (shells out to the
system `tesseract` binary), because CAD schedules often draw text as vector paths that have no
real text layer at all, so PyMuPDF's normal text extraction returns nothing for those labels.

- **When it runs:** automatically for any page with no extractable text layer, or on every page
  if you enable "Always OCR (ignore embedded text)" in the frontend (`force_ocr=true`), which is
  the option to use for drawings where the schedule grid itself has no real text objects.
- **Render:** `render.yaml` installs `tesseract-ocr` via `apt-get` during the build. If your
  Render plan/image blocks `apt-get` in `buildCommand`, switch to a Docker-based Render service
  with a Dockerfile that installs `tesseract-ocr`.
- **Local dev:** install it with `sudo apt-get install tesseract-ocr` (Debian/Ubuntu) or the
  equivalent for your OS, then restart `uvicorn`.
- OCR can be disabled entirely by sending `enable_ocr=false`. If OCR is requested but Tesseract
  isn't installed, the API still responds normally with `used_ocr: false` and an `ocr_error`
  message on the affected page instead of failing the request.


