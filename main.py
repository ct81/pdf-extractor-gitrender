import io
import re

import pymupdf  # PyMuPDF
import pytesseract
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

# Row-label tokens used to recognize a storey/level, e.g. "30TH", "1ST STY. FL. LVL",
# "UPPER ROOF", "FOUNDATION BASE" — these drawings label storeys as ROW headers,
# not as a "Storey" table column, so plain header-name matching cannot find them.
STOREY_TOKEN_RE = re.compile(
    r"(\bGROUND\b|\bROOF\b|\bFOUNDATION\b|\bBASEMENT\b|\bMEZZ(ANINE)?\b|"
    r"\bB\d{1,2}\b|\d{1,3}\s*(ST|ND|RD|TH)\b|\bSTOREY\b|\bSTY\b|\bLEVEL\b|"
    r"\bLVL\b|\bTIER\b)",
    re.IGNORECASE,
)

# Legend-row token used to find the row that lists column/beam/wall "MARKS",
# whose other cells (not a header) hold the actual marking codes.
MARK_LABEL_RE = re.compile(r"\bMARK", re.IGNORECASE)

app = FastAPI(title="High-Precision Dynamic PDF Coordinates Extractor API")

# Enable CORS for cross-origin web requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "status": "online",
        "message": "Python PyMuPDF Extractor Backend running",
    }


def build_dynamic_coordinate_matrix(
    words, x_gap_threshold=35, y_gap_threshold=8
):
    """Dynamically clusters extracted X,Y word coordinates into a 2D matrix

    table grid without hardcoded pixel boundaries or static column names.
    """
    if not words:
        return {"total_columns": 0, "column_anchors": [], "rows": []}

    # 1. Cluster X-coordinates into Dynamic Column Anchors
    x_positions = sorted([w["x0"] for w in words])
    columns = []

    for x in x_positions:
        matched = None
        for col in columns:
            if abs(col["mean"] - x) <= x_gap_threshold:
                matched = col
                break
        if matched:
            matched["count"] += 1
            matched["mean"] = (
                (matched["mean"] * (matched["count"] - 1)) + x
            ) / matched["count"]
            matched["min_x"] = min(matched["min_x"], x)
            matched["max_x"] = max(matched["max_x"], x)
        else:
            columns.append({"mean": x, "min_x": x, "max_x": x, "count": 1})

    columns.sort(key=lambda c: c["mean"])

    # 2. Cluster Y-coordinates into Row Bands (Top-to-Bottom)
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows = []

    for w in sorted_words:
        matched_row = None
        for r in rows:
            if abs(r["top"] - w["top"]) <= y_gap_threshold:
                matched_row = r
                break
        if matched_row:
            matched_row["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})

    # 3. Project Words into Matrix Grid
    matrix_rows = []
    for r_idx, r in enumerate(rows):
        row_cells = ["" for _ in range(len(columns))]
        r["words"].sort(key=lambda w: w["x0"])

        for w in r["words"]:
            best_col_idx = 0
            min_dist = float("inf")
            for c_idx, c in enumerate(columns):
                dist = abs(c["mean"] - w["x0"])
                if dist < min_dist:
                    min_dist = dist
                    best_col_idx = c_idx

            if row_cells[best_col_idx] == "":
                row_cells[best_col_idx] = w["text"]
            else:
                row_cells[best_col_idx] += " " + w["text"]

        matrix_rows.append(
            {
                "row_id": r_idx + 1,
                "y_top": round(r["top"], 2),
                "cells": row_cells,
            }
        )

    return {
        "total_columns": len(columns),
        "column_anchors": [round(c["mean"], 2) for c in columns],
        "rows": matrix_rows,
    }


def build_schedule_tables(extracted_tables, spatial_grid):
    """Normalize detected PDF tables and identify Storey and Marking columns."""
    schedule_tables = []
    for table_number, table in enumerate(extracted_tables, start=1):
        rows = [[str(cell or "").strip() for cell in row] for row in table]
        if not rows:
            continue

        header_index = 0
        for row_index, row in enumerate(rows[:5]):
            labels = [cell.lower() for cell in row]
            if any("storey" in cell or "story" in cell or "floor" in cell for cell in labels):
                header_index = row_index
                break

        headers = [cell or f"Column_{index + 1}" for index, cell in enumerate(rows[header_index])]
        normalized_headers = [header.lower() for header in headers]
        storey_index = next(
            (index for index, header in enumerate(normalized_headers)
             if "storey" in header or "story" in header or "floor" in header),
            None,
        )
        marking_index = next(
            (index for index, header in enumerate(normalized_headers)
             if "marking" in header or "mark" in header),
            None,
        )

        table_rows = []
        for row in rows[header_index + 1:]:
            if not any(row):
                continue
            cells = (row + [""] * len(headers))[:len(headers)]
            table_rows.append({
                "cells": cells,
                "storey": cells[storey_index] if storey_index is not None else "",
                "marking": cells[marking_index] if marking_index is not None else "",
            })

        schedule_tables.append({
            "table_number": table_number,
            "source": "pdf_table",
            "headers": headers,
            "rows": table_rows,
        })

    if not schedule_tables and spatial_grid["rows"]:
        grid_rows = spatial_grid["rows"]
        header_index = next(
            (index for index, row in enumerate(grid_rows[:5])
             if any("storey" in cell.lower() or "story" in cell.lower()
                    or "floor" in cell.lower() or "mark" in cell.lower()
                    for cell in row["cells"])),
            0,
        )
        headers = [cell or f"Column_{index + 1}"
                   for index, cell in enumerate(grid_rows[header_index]["cells"])]
        normalized_headers = [header.lower() for header in headers]
        storey_index = next(
            (index for index, header in enumerate(normalized_headers)
             if "storey" in header or "story" in header or "floor" in header),
            None,
        )
        marking_index = next(
            (index for index, header in enumerate(normalized_headers) if "mark" in header),
            None,
        )
        table_rows = []
        for row in grid_rows[header_index + 1:]:
            cells = (row["cells"] + [""] * len(headers))[:len(headers)]
            if any(cells):
                table_rows.append({
                    "cells": cells,
                    "storey": cells[storey_index] if storey_index is not None else "",
                    "marking": cells[marking_index] if marking_index is not None else "",
                })
        schedule_tables.append({
            "table_number": 1,
            "source": "coordinates",
            "headers": headers,
            "rows": table_rows,
        })

    return schedule_tables


def build_storey_marking_pivot(spatial_grid):
    """Reconstruct a Storey x Marking schedule directly from the word-coordinate
    matrix. Many CAD/structural schedules place storeys as ROW labels and marks
    as a legend ROW (e.g. "COLUMN MARKS" followed by codes in the other cells of
    that same row) instead of using conventional column headers, so find_tables()
    and header-name matching cannot detect them. This pivots row/column position
    instead of relying on header text.
    """
    rows = spatial_grid.get("rows", [])
    column_anchors = spatial_grid.get("column_anchors", [])
    if not rows or not column_anchors:
        return []

    # 1. Find the marks legend row and forward-fill each column to its mark code,
    #    since a mark label is often centered under only the first of several
    #    columns that belong to it (merged cell in the source drawing).
    marks_row = None
    mark_label_column = None
    for row in rows:
        for col_idx, cell in enumerate(row["cells"]):
            if cell and MARK_LABEL_RE.search(cell):
                marks_row = row
                mark_label_column = col_idx
                break
        if marks_row:
            break

    mark_by_column = {}
    if marks_row:
        last_mark = None
        for col_idx, cell in enumerate(marks_row["cells"]):
            if col_idx == mark_label_column:
                continue
            if cell:
                last_mark = cell
            if last_mark:
                mark_by_column[col_idx] = last_mark

    # 2. For every remaining row, detect a storey label anywhere in the row's
    #    leading cells, then pair each data cell with its forward-filled mark.
    pivot_rows = []
    for row in rows:
        if marks_row and row["row_id"] == marks_row["row_id"]:
            continue

        storey_label = None
        storey_column = None
        for col_idx, cell in enumerate(row["cells"]):
            if cell and STOREY_TOKEN_RE.search(cell):
                storey_label = cell
                storey_column = col_idx
                break

        if storey_label is None:
            continue

        for col_idx, cell in enumerate(row["cells"]):
            if col_idx == storey_column or not cell:
                continue
            x_anchor = column_anchors[col_idx] if col_idx < len(column_anchors) else None
            pivot_rows.append(
                {
                    "storey": storey_label,
                    "marking": mark_by_column.get(col_idx, ""),
                    "value": cell,
                    "row_id": row["row_id"],
                    "column_index": col_idx,
                    "y_top": row["y_top"],
                    "x": x_anchor,
                    "coordinate": (
                        f"(x={x_anchor}, y={row['y_top']})" if x_anchor is not None else ""
                    ),
                }
            )

    return pivot_rows


def extract_words_via_ocr(page, dpi=200, language="eng"):
    """OCR overlapping grayscale page tiles and map word boxes to PDF points."""
    scale = dpi / 72
    page_rect = page.rect
    tile_size = 900
    overlap = 24
    words = []

    try:
        y0 = page_rect.y0
        while y0 < page_rect.y1:
            y1 = min(y0 + tile_size, page_rect.y1)
            x0 = page_rect.x0
            while x0 < page_rect.x1:
                x1 = min(x0 + tile_size, page_rect.x1)
                core = pymupdf.Rect(x0, y0, x1, y1)
                clip = pymupdf.Rect(
                    max(page_rect.x0, x0 - overlap),
                    max(page_rect.y0, y0 - overlap),
                    min(page_rect.x1, x1 + overlap),
                    min(page_rect.y1, y1 + overlap),
                )
                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    clip=clip,
                    colorspace=pymupdf.csGRAY,
                    alpha=False,
                )
                image = Image.frombytes("L", [pix.width, pix.height], pix.samples)
                ocr_data = pytesseract.image_to_data(
                    image, lang=language, output_type=pytesseract.Output.DICT
                )
                image.close()

                origin_x = pix.x / scale
                origin_y = pix.y / scale
                for i, text in enumerate(ocr_data["text"]):
                    text = text.strip()
                    if not text:
                        continue
                    left = origin_x + ocr_data["left"][i] / scale
                    top = origin_y + ocr_data["top"][i] / scale
                    right = left + ocr_data["width"][i] / scale
                    bottom = top + ocr_data["height"][i] / scale
                    center_x = (left + right) / 2
                    center_y = (top + bottom) / 2
                    if not (x0 <= center_x < x1 and y0 <= center_y < y1):
                        continue
                    words.append(
                        (
                            left,
                            top,
                            right,
                            bottom,
                            text,
                            ocr_data["block_num"][i],
                            ocr_data["line_num"][i],
                            ocr_data["word_num"][i],
                        )
                    )
                x0 = x1
            y0 = y1
    except Exception as exc:
        return [], str(exc)

    return words, None


@app.post("/extract-coordinates")
async def extract_coordinates(
    file: UploadFile = File(...),
    x_gap_threshold: float = Form(35.0),
    y_gap_threshold: float = Form(8.0),
    enable_ocr: bool = Form(True),
    force_ocr: bool = Form(False),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400, detail="Only PDF files are supported."
        )

    try:
        pdf_bytes = await file.read()
        extracted_pages = []

        # Open byte stream directly using PyMuPDF
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

        for page_idx, page in enumerate(doc):
            rect = page.rect

            # 1. High-precision word extraction via PyMuPDF
            # page.get_text("words") returns tuples: (x0, y0, x1, y1, word, block_no, line_no, word_no)
            raw_words = [] if force_ocr else page.get_text("words")

            # 1b. OCR fallback: run when forced, or when the page has no text layer
            # at all (scanned/image-only page or CAD text drawn as vector paths).
            used_ocr = False
            ocr_error = None
            if enable_ocr and (force_ocr or not raw_words):
                ocr_words, ocr_error = extract_words_via_ocr(page)
                if ocr_words:
                    raw_words = ocr_words
                    used_ocr = True
                elif force_ocr:
                    # OCR failed (e.g. Tesseract not installed) - fall back to any real text.
                    raw_words = page.get_text("words")

            words_data = []
            for w in raw_words:
                x0, y0, x1, y1, text, block_no, line_no, word_no = w
                words_data.append(
                    {
                        "text": text,
                        "x0": round(x0, 2),
                        "top": round(y0, 2),
                        "x1": round(x1, 2),
                        "bottom": round(y1, 2),
                        "width": round(x1 - x0, 2),
                        "height": round(y1 - y0, 2),
                        "coordinate": f"({x0:.2f}, {y0:.2f})-({x1:.2f}, {y1:.2f})",
                        "block_no": block_no,
                        "line_no": line_no,
                    }
                )

            # 2. Extract block structures (blocks: x0, y0, x1, y1, text, block_no, block_type)
            raw_blocks = page.get_text("blocks")
            blocks_data = []
            for b in raw_blocks:
                if (
                    b[6] == 0
                ):  # Filter for text blocks (type 0 = text, type 1 = image)
                    blocks_data.append(
                        {
                            "bbox": [
                                round(b[0], 2),
                                round(b[1], 2),
                                round(b[2], 2),
                                round(b[3], 2),
                            ],
                            "text": b[4].strip(),
                            "block_no": b[5],
                        }
                    )

            # Table detection scans PDF vector paths, which can exhaust small
            # Render instances on CAD pages; OCR/grid output already handles those.
            extracted_tables = []
            if not used_ocr and len(raw_words) >= 100:
                try:
                    found_tables = page.find_tables()
                    extracted_tables = (
                        [t.extract() for t in found_tables] if found_tables else []
                    )
                except Exception:
                    extracted_tables = []

            # 4. Construct dynamic spatial coordinate grid
            spatial_grid = build_dynamic_coordinate_matrix(
                words_data,
                x_gap_threshold=x_gap_threshold,
                y_gap_threshold=y_gap_threshold,
            )

            extracted_pages.append(
                {
                    "page_number": page_idx + 1,
                    "width": round(rect.width, 2),
                    "height": round(rect.height, 2),
                    "raw_words_count": len(words_data),
                    "used_ocr": used_ocr,
                    "ocr_error": ocr_error,
                    "blocks": blocks_data,
                    "words": words_data,
                    "tables": extracted_tables,
                    "schedule_tables": build_schedule_tables(extracted_tables, spatial_grid),
                    "storey_marking_schedule": build_storey_marking_pivot(spatial_grid),
                    "spatial_grid": spatial_grid,
                }
            )

        doc.close()

        return {
            "status": "success",
            "filename": file.filename,
            "total_pages": len(extracted_pages),
            "pages": extracted_pages,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))







# from fastapi import FastAPI, UploadFile, File, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# import pdfplumber
# import io

# app = FastAPI(title="High-Precision Dynamic PDF Coordinates Extractor API")

# # Enable CORS for cross-origin web requests
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# @app.get("/")
# def root():
#     return {"status": "online", "message": "Python PDF Extractor Backend running on Render"}

# def build_dynamic_coordinate_matrix(words, x_gap_threshold=35, y_gap_threshold=8):
#     """
#     Dynamically clusters extracted X,Y word coordinates into a 2D matrix 
#     table grid without hardcoded pixel boundaries or static column names.
#     """
#     if not words:
#         return {"total_columns": 0, "column_anchors": [], "rows": []}

#     # 1. Cluster X-coordinates into Dynamic Column Anchors
#     x_positions = sorted([w["x0"] for w in words])
#     columns = []

#     for x in x_positions:
#         matched = None
#         for col in columns:
#             if abs(col["mean"] - x) <= x_gap_threshold:
#                 matched = col
#                 break
#         if matched:
#             matched["count"] += 1
#             matched["mean"] = ((matched["mean"] * (matched["count"] - 1)) + x) / matched["count"]
#             matched["min_x"] = min(matched["min_x"], x)
#             matched["max_x"] = max(matched["max_x"], x)
#         else:
#             columns.append({"mean": x, "min_x": x, "max_x": x, "count": 1})

#     columns.sort(key=lambda c: c["mean"])

#     # 2. Cluster Y-coordinates into Row Bands (Top-to-Bottom)
#     sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
#     rows = []

#     for w in sorted_words:
#         matched_row = None
#         for r in rows:
#             if abs(r["top"] - w["top"]) <= y_gap_threshold:
#                 matched_row = r
#                 break
#         if matched_row:
#             matched_row["words"].append(w)
#         else:
#             rows.append({"top": w["top"], "words": [w]})

#     # 3. Project Words into Matrix Grid
#     matrix_rows = []
#     for r_idx, r in enumerate(rows):
#         row_cells = ["" for _ in range(len(columns))]
#         r["words"].sort(key=lambda w: w["x0"])

#         for w in r["words"]:
#             best_col_idx = 0
#             min_dist = float("inf")
#             for c_idx, c in enumerate(columns):
#                 dist = abs(c["mean"] - w["x0"])
#                 if dist < min_dist:
#                     min_dist = dist
#                     best_col_idx = c_idx

#             if row_cells[best_col_idx] == "":
#                 row_cells[best_col_idx] = w["text"]
#             else:
#                 row_cells[best_col_idx] += " " + w["text"]

#         matrix_rows.append({
#             "row_id": r_idx + 1,
#             "y_top": round(r["top"], 2),
#             "cells": row_cells
#         })

#     return {
#         "total_columns": len(columns),
#         "column_anchors": [round(c["mean"], 2) for c in columns],
#         "rows": matrix_rows
#     }

# @app.post("/extract-coordinates")
# async def extract_coordinates(file: UploadFile = File(...)):
#     if not file.filename.lower().endswith(".pdf"):
#         raise HTTPException(status_code=400, detail="Only PDF files are supported.")

#     try:
#         pdf_bytes = await file.read()
#         extracted_pages = []

#         with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
#             for page_idx, page in enumerate(pdf.pages):
#                 # 1. High-precision word coordinate extraction
#                 words = page.extract_words(
#                     x_tolerance=2,
#                     y_tolerance=3,
#                     keep_blank_chars=False
#                 )

#                 words_data = []
#                 for w in words:
#                     words_data.append({
#                         "text": w["text"],
#                         "x0": round(w["x0"], 2),
#                         "top": round(w["top"], 2),
#                         "x1": round(w["x1"], 2),
#                         "bottom": round(w["bottom"], 2),
#                         "width": round(w["width"], 2),
#                         "height": round(w["height"], 2)
#                     })

#                 # 2. Extract vector tables & construct dynamic spatial coordinate grid
#                 tables = page.extract_tables()
#                 spatial_grid = build_dynamic_coordinate_matrix(words_data)

#                 extracted_pages.append({
#                     "page_number": page_idx + 1,
#                     "width": round(page.width, 2),
#                     "height": round(page.height, 2),
#                     "raw_words_count": len(words_data),
#                     "words": words_data,
#                     "tables": tables,
#                     "spatial_grid": spatial_grid
#                 })

#         return {
#             "status": "success",
#             "filename": file.filename,
#             "total_pages": len(extracted_pages),
#             "pages": extracted_pages
#         }

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))






# from fastapi import FastAPI, UploadFile, File, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# import pdfplumber
# import io
# import re

# app = FastAPI(title="High-Precision PDF Coordinates Extractor API")

# # Enable CORS for cross-origin web requests from GitHub Pages / Vercel / Local HTML
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# @app.get("/")
# def root():
#     return {"status": "online", "message": "Python PDF Extractor Backend running on Render"}

# def parse_cad_stream(text_block):
#     keywords = ["ARRANGEMENT", "SIZE", "MAIN BAR", "CAGE CODE", "SPLICE BAR", "SHEAR LINK", "DA1-1", "DA1-2", "Gk", "Qk"]
#     regex_pattern = f"({'|'.join(keywords)})"
#     parts = re.split(regex_pattern, text_block)
    
#     parsed = []
#     if len(parts) > 1:
#         for i in range(1, len(parts), 2):
#             key = parts[i]
#             val_str = parts[i+1] if i+1 < len(parts) else ""
#             tokens = re.findall(r"(TYPE \w+|STUMP \w+|\d+x\d+|\d+H\d+|C\d+[A-Z]* \d+|H\d+-\d+|\d+|(?:AS|SAME) BELOW|-)", val_str, re.IGNORECASE)
#             if not tokens:
#                 tokens = [val_str.strip()]
#             parsed.append({"key": key, "tokens": tokens})
#     return parsed

# @app.post("/extract-coordinates")
# async def extract_coordinates(file: UploadFile = File(...)):
#     if not file.filename.lower().endswith(".pdf"):
#         raise HTTPException(status_code=400, detail="Only PDF files are supported.")

#     try:
#         pdf_bytes = await file.read()
#         extracted_pages = []

#         with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
#             for page_idx, page in enumerate(pdf.pages):
#                 # 1. High-precision word coordinate extraction
#                 words = page.extract_words(
#                     x_tolerance=2,
#                     y_tolerance=3,
#                     keep_blank_chars=False
#                 )

#                 words_data = []
#                 for w in words:
#                     words_data.append({
#                         "text": w["text"],
#                         "x0": round(w["x0"], 2),
#                         "top": round(w["top"], 2),
#                         "x1": round(w["x1"], 2),
#                         "bottom": round(w["bottom"], 2),
#                         "width": round(w["width"], 2),
#                         "height": round(w["height"], 2)
#                     })

#                 # 2. Native Table extraction
#                 tables = page.extract_tables()

#                 # Check for CAD concatenated stream text
#                 raw_text_full = page.extract_text() or ""
#                 cad_parsed_rows = []
#                 if "ARRANGEMENT" in raw_text_full and "MAIN BAR" in raw_text_full:
#                     cad_parsed_rows = parse_cad_stream(raw_text_full)

#                 extracted_pages.append({
#                     "page_number": page_idx + 1,
#                     "width": round(page.width, 2),
#                     "height": round(page.height, 2),
#                     "raw_words_count": len(words_data),
#                     "words": words_data,
#                     "tables": tables,
#                     "cad_parsed": cad_parsed_rows
#                 })

#         return {
#             "status": "success",
#             "filename": file.filename,
#             "total_pages": len(extracted_pages),
#             "pages": extracted_pages
#         }

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
