from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import io

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
    return {"status": "online", "message": "Python PDF Extractor Backend running on Render"}

def build_dynamic_coordinate_matrix(words, x_gap_threshold=35, y_gap_threshold=8):
    """
    Dynamically clusters extracted X,Y word coordinates into a 2D matrix 
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
            matched["mean"] = ((matched["mean"] * (matched["count"] - 1)) + x) / matched["count"]
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

        matrix_rows.append({
            "row_id": r_idx + 1,
            "y_top": round(r["top"], 2),
            "cells": row_cells
        })

    return {
        "total_columns": len(columns),
        "column_anchors": [round(c["mean"], 2) for c in columns],
        "rows": matrix_rows
    }

@app.post("/extract-coordinates")
async def extract_coordinates(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    try:
        pdf_bytes = await file.read()
        extracted_pages = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                # 1. High-precision word coordinate extraction
                words = page.extract_words(
                    x_tolerance=2,
                    y_tolerance=3,
                    keep_blank_chars=False
                )

                words_data = []
                for w in words:
                    words_data.append({
                        "text": w["text"],
                        "x0": round(w["x0"], 2),
                        "top": round(w["top"], 2),
                        "x1": round(w["x1"], 2),
                        "bottom": round(w["bottom"], 2),
                        "width": round(w["width"], 2),
                        "height": round(w["height"], 2)
                    })

                # 2. Extract vector tables & construct dynamic spatial coordinate grid
                tables = page.extract_tables()
                spatial_grid = build_dynamic_coordinate_matrix(words_data)

                extracted_pages.append({
                    "page_number": page_idx + 1,
                    "width": round(page.width, 2),
                    "height": round(page.height, 2),
                    "raw_words_count": len(words_data),
                    "words": words_data,
                    "tables": tables,
                    "spatial_grid": spatial_grid
                })

        return {
            "status": "success",
            "filename": file.filename,
            "total_pages": len(extracted_pages),
            "pages": extracted_pages
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
