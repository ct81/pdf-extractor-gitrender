from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import io
import re
from collections import defaultdict

app = FastAPI(title="Dynamic Zero-Hardcoded PDF Coordinates Extractor API")

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
    return {"status": "online", "message": "Zero-Hardcoded PDF Extractor Backend running on Render"}

def detect_cad_keywords_dynamically(text):
    """
    Dynamically identifies potential header/parameter keys from text 
    by detecting repeating UPPERCASE or TitleCase keywords preceding values.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    potential_keys = set()
    
    for line in lines:
        # Match leading word groups that look like table labels (e.g., ARRANGEMENT, MAIN BAR, SIZE)
        matches = re.findall(r'^[A-Z0-9\s/_\-]{2,20}(?=\s|\d|[a-z]|$)', line)
        for m in matches:
            m_clean = m.strip()
            if len(m_clean) > 2 and not m_clean.isdigit():
                potential_keys.add(m_clean)
                
    return sorted(list(potential_keys), key=len, reverse=True)

def parse_cad_stream_dynamic(text_block):
    """
    Dynamically parses concatenated CAD stream blocks without hardcoding key names.
    """
    keys = detect_cad_keywords_dynamically(text_block)
    if not keys:
        return []

    regex_pattern = f"({'|'.join(re.escape(k) for k in keys)})"
    parts = re.split(regex_pattern, text_block)
    
    parsed = []
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            key = parts[i]
            val_str = parts[i+1] if i+1 < len(parts) else ""
            # Tokenize values dynamically
            tokens = [t.strip() for t in re.split(r'\s{2,}|\n|,', val_str) if t.strip()]
            if not tokens:
                tokens = [val_str.strip()]
            parsed.append({"key": key, "tokens": tokens})
    return parsed

def build_dynamic_spatial_matrix(words, x_gap_threshold=25, y_gap_threshold=6):
    """
    Dynamically clusters X-column centers and Y-row bands using 1D Mean-Shift clustering.
    Zero hardcoded coordinates or column names.
    """
    if not words:
        return []

    # 1. Dynamic Column Center Detection (X-axis Mean-Shift Clustering)
    x_positions = sorted([w["x0"] for w in words])
    columns = []

    for x in x_positions:
        matched_col = None
        for col in columns:
            if abs(col["mean"] - x) <= x_gap_threshold:
                matched_col = col
                break
        
        if matched_col:
            matched_col["count"] += 1
            matched_col["mean"] = ((matched_col["mean"] * (matched_col["count"] - 1)) + x) / matched_col["count"]
            matched_col["min_x"] = min(matched_col["min_x"], x)
            matched_col["max_x"] = max(matched_col["max_x"], x)
        else:
            columns.append({"mean": x, "min_x": x, "max_x": x, "count": 1})

    # Sort columns strictly left-to-right
    columns.sort(key=lambda c: c["mean"])

    # 2. Dynamic Row Banding (Y-axis Top-to-Bottom Grouping)
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

    # 3. Project Words into Dynamic Matrix
    matrix = []
    for r_idx, r in enumerate(rows):
        row_cells = ["" for _ in range(len(columns))]
        
        # Sort words in row left-to-right
        r["words"].sort(key=lambda w: w["x0"])

        for w in r["words"]:
            # Find closest dynamic column
            best_col_idx = 0
            min_dist = float("inf")
            for c_idx, c in enumerate(columns):
                dist = abs(c["mean"] - w["x0"])
                if dist < min_dist:
                    min_dist = dist;
                    best_col_idx = c_idx

            if row_cells[best_col_idx] == "":
                row_cells[best_col_idx] = w["text"]
            else:
                row_cells[best_col_idx] += " " + w["text"]

        matrix.append({
            "row_index": r_idx + 1,
            "y_top": round(r["top"], 2),
            "cells": row_cells
        })

    return {
        "detected_columns_count": len(columns),
        "column_anchors": [round(c["mean"], 2) for c in columns],
        "matrix_rows": matrix
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
                # 1. Extract raw words with exact bounding box coordinates
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

                # 2. Extract native PDF vector tables
                tables = page.extract_tables()

                # 3. Dynamic Spatial Matrix Construction (Zero Hardcoding)
                spatial_grid = build_dynamic_spatial_matrix(words_data)

                # 4. Dynamic CAD Stream Text Parsing
                raw_text_full = page.extract_text() or ""
                cad_parsed = parse_cad_stream_dynamic(raw_text_full)

                extracted_pages.append({
                    "page_number": page_idx + 1,
                    "width": round(page.width, 2),
                    "height": round(page.height, 2),
                    "raw_words_count": len(words_data),
                    "words": words_data,
                    "tables": tables,
                    "cad_parsed": cad_parsed,
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
