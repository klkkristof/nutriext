# main.py - IMPROVED VERSION
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import os, io, json, re, logging, tempfile
from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import httpx
from groq import Groq

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("extractor")

# --- FastAPI ---
app = FastAPI(
    title="PDF Allergen & Nutrition Extractor",
    description="Extract allergen and nutritional information from PDFs using Groq AI",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*"  # Remove in production, specify exact domains
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # Upgraded to 70B for better accuracy
POPPLER_BIN = os.getenv("POPPLER_PATH", r"C:\Program Files\Poppler\Library\bin")
OCR_LANG = os.getenv("OCR_LANG", "hun+eng")  # Hungarian + English
MAX_PDF_SIZE_MB = int(os.getenv("MAX_PDF_SIZE_MB", "10"))
OCR_DPI = int(os.getenv("OCR_DPI", "300"))  # Increased for better quality
MAX_OCR_PAGES = int(os.getenv("MAX_OCR_PAGES", "10"))

# Validate API key
if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key":
    logger.warning("⚠️  GROQ_API_KEY not configured! Set it in environment variables.")

# --- Enhanced System Prompt ---
SYSTEM_PROMPT = """You are a highly specialized AI system for extracting structured information from food product labels and nutritional specifications.

Your task is to analyze the extracted text of a food product document (e.g., PDF, OCR result) and return a complete structured JSON response following the exact schema below.

==========================
EXTRACTION INSTRUCTIONS
==========================

1. **Purpose**  
   Identify and extract all key information related to product identity, ingredients, allergens, and nutrition facts.  
   The goal is to produce a clean, structured JSON for database storage or API integration.

2. **Text Input**  
   You will receive plain text extracted from food product PDFs. The text may contain both Hungarian and English words (e.g., "összetevők", "ingredients", "energia", "energy").

3. **Detection Strategy**
   - Focus on the factual information — do not infer or assume values.
   - If multiple values or tables appear, choose the **most complete per 100g / 100ml** section.
   - Recognize both Hungarian and English keywords (e.g., “energia”, “energy”, “zsír”, “fat”, “fehérje”, “protein”).
   - Convert commas to decimal points (4,5 → 4.5).
   - Remove units (“g”, “kJ”, “kcal”) from numeric values.
   - If salt value is given, compute sodium ≈ salt × 0.4 (in grams).

4. **Allergen Identification**
   - Analyze ingredient lists and allergen statements.
   - Detect phrases such as “Allergens:”, “Contains:”, “May contain:”, “Allergén információ:”, “Nyomokban tartalmazhat”.
   - Distinguish between:
     - `"contains"` → explicitly stated or clearly present in ingredients.
     - `"may_contain"` → indicated as possible traces.
   - Check both English and Hungarian synonyms.
   - If unsure or unclear → mark `present=false` and `contains_or_may_contain=null`.

5. **Confidence**
   - `"high"` → clear, explicit data extracted.
   - `"medium"` → minor uncertainty (e.g., incomplete table).
   - `"low"` → text ambiguous or noisy.

==========================
OUTPUT REQUIREMENTS
==========================

ALLERGEN IDENTIFICATION:
- The PDF may express allergen presence using symbols or keywords:
  - "+" or "tartalmaz" → means "contains"
  - "nyomokban" or "may contain" → means "may_contain"
  - "-" or "mentes" → means "absent" (present = false)
- Table headings such as "Allergens information / Allergén információk" indicate the allergen section.
- Each allergen can appear in bilingual form (e.g. "milk protein / tejfehérje", "soy protein / szója fehérje").
- Always detect the allergen **even if it only appears in Hungarian**.
- When multiple allergens are listed, map them to the following standard 10 classes:
  1. Gluten (wheat, rye, barley, oats, búza, rozs, árpa, zab)
  2. Eggs (tojás)
  3. Crustaceans (shrimp, crab, lobster, rákfélék)
  4. Fish (hal)
  5. Peanuts (földimogyoró)
  6. Soybeans (soy, szója)
  7. Milk (dairy, lactose, tej, tejfehérje)
  8. Nuts (tree nuts: dió, mandula, mogyoró, kesudió, pekándió, pisztácia)
  9. Celery (zeller)
  10. Mustard (mustár)
- If allergen has a “+” mark, or the text says “contains”, mark:
  `"present": true, "contains_or_may_contain": "contains"`
- If allergen is marked “nyomokban”, “may contain”, or has a “+” with a note about traces, mark:
  `"present": true, "contains_or_may_contain": "may_contain"`
- If allergen is marked “-” or “mentes”, mark:
  `"present": false, "contains_or_may_contain": null`
- If ambiguous or missing, mark `"present": false`.
- When possible, fill `"source"` with the Hungarian ingredient name (e.g. "búzaliszt", "tejfehérje", "szója fehérje").

- When an allergen is mentioned together with the phrase “nyomokban”, “may contain”, or “tartalmazhat”,
  always set:
  "present": true,
  "contains_or_may_contain": "may_contain".

- When the text says “tartalmaz”, “contains”, or the allergen has a “+” mark without mention of traces,
  set:
  "present": true,
  "contains_or_may_contain": "contains".

- If an allergen appears in a list with both “tartalmaz” and “nyomokban” mentions, prefer “may_contain”.
  (Assume trace contamination if any uncertainty exists.)

Return ONLY valid JSON in the exact format below.
Do NOT include any commentary, explanations, or text outside the JSON.
All numeric values must be plain numbers (no units, no strings).
Use `null` for any missing or uncertain values.

{
  "product_name": "string or null",
  "brand": "string or null",
  "net_quantity": {"amount": number, "unit": "string"} or null,
  "ingredients_text": "string or null",
  "allergens": [
    {
      "name": "Gluten",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Eggs",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Crustaceans",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Fish",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Peanuts",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Soybeans",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Milk",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Nuts",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Celery",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    },
    {
      "name": "Mustard",
      "present": true/false,
      "source": "string or null",
      "contains_or_may_contain": "contains" or "may_contain" or null
    }
  ],
  "nutrition": {
    "basis": "per_100g" or "per_serving" or null,
    "energy_kj": number or null,
    "energy_kcal": number or null,
    "fat_g": number or null,
    "saturated_fat_g": number or null,
    "carbohydrate_g": number or null,
    "sugars_g": number or null,
    "protein_g": number or null,
    "fiber_g": number or null,
    "salt_g": number or null,
    "sodium_g": number or null,
    "serving_size": {"amount": number, "unit": "string"} or null
  },
  "warnings": ["string list of warnings, if any"],
  "notes": "string or null",
  "meta": {"confidence": "high" or "medium" or "low"}
}

==========================
ADDITIONAL GUIDELINES
==========================
- Do not hallucinate data that is not explicitly found.
- Prefer null over guessing.
- Use floating-point numbers (not strings) for nutrition values.
- Preserve ingredient order and special characters in the ingredient list.
- When multiple languages are mixed, prioritize Hungarian if available.
- Output **MUST** be strictly valid JSON.
"""

# --- Pydantic Models ---
class Quantity(BaseModel):
    amount: Optional[float] = None
    unit: Optional[str] = None

class AllergenItem(BaseModel):
    name: str
    present: bool
    source: Optional[str] = None
    contains_or_may_contain: Optional[str] = None  # "contains" | "may_contain"

class Nutrition(BaseModel):
    basis: Optional[str] = None  # "per_100g" | "per_serving"
    energy_kj: Optional[float] = None
    energy_kcal: Optional[float] = None
    fat_g: Optional[float] = None
    saturated_fat_g: Optional[float] = None
    carbohydrate_g: Optional[float] = None
    sugars_g: Optional[float] = None
    protein_g: Optional[float] = None
    fiber_g: Optional[float] = None
    salt_g: Optional[float] = None
    sodium_g: Optional[float] = None
    serving_size: Optional[Quantity] = None

class ExtractResponse(BaseModel):
    product_name: Optional[str] = None
    brand: Optional[str] = None
    net_quantity: Optional[Quantity] = None
    ingredients_text: Optional[str] = None
    allergens: List[AllergenItem] = Field(default_factory=list)
    nutrition: Optional[Nutrition] = None
    warnings: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

# --- PDF Text Extraction ---
def extract_text_from_pdf(pdf_path: str) -> tuple[str, str]:
    """
    Extract text from PDF, trying direct extraction first, then OCR.
    Returns: (text, mode) where mode is 'text' or 'ocr'
    """
    # Try direct text extraction first (fast)
    text = _extract_text_direct(pdf_path)
    
    if text and len(text.strip()) > 100:  # Reasonable amount of text found
        logger.info(f"✓ Extracted {len(text)} chars using direct method")
        return text, "text"
    
    # Fall back to OCR (slower but handles scanned PDFs)
    logger.info("→ Direct extraction insufficient, using OCR...")
    text = _extract_text_ocr(pdf_path)
    
    if text:
        logger.info(f"✓ Extracted {len(text)} chars using OCR")
        return text, "ocr"
    
    return "", "empty"

def _extract_text_direct(pdf_path: str) -> str:
    """Direct text extraction using pdfplumber"""
    chunks = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    chunks.append(f"--- Page {page_num} ---\n{text}\n")
        return "".join(chunks).strip()
    except Exception as e:
        logger.error(f"Direct extraction error: {e}")
        return ""

def _extract_text_ocr(pdf_path: str) -> str:
    """OCR extraction using Tesseract"""
    try:
        # Convert PDF to images
        images = convert_from_path(
            pdf_path,
            dpi=OCR_DPI,
            poppler_path=POPPLER_BIN if os.path.exists(POPPLER_BIN) else None
        )
        
        texts = []
        for page_num, image in enumerate(images[:MAX_OCR_PAGES], 1):
            logger.info(f"  OCR processing page {page_num}/{len(images[:MAX_OCR_PAGES])}")
            text = pytesseract.image_to_string(image, lang=OCR_LANG)
            if text:
                texts.append(f"--- Page {page_num} ---\n{text}\n")
        
        return "".join(texts).strip()
    
    except Exception as e:
        logger.error(f"OCR extraction error: {e}")
        return ""

# --- Groq AI Processing ---
def extract_with_groq(raw_text: str, timeout_seconds: int = 60) -> Dict[str, Any]:
    """
    Send extracted text to Groq for AI analysis
    """
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key":
        raise RuntimeError("GROQ_API_KEY is not configured. Please set it in environment variables.")
    
    # Truncate text if too long (keep beginning and end)
    max_chars = 15000  # Groq context limit consideration
    if len(raw_text) > max_chars:
        half = max_chars // 2
        raw_text = raw_text[:half] + "\n\n... [TRUNCATED] ...\n\n" + raw_text[-half:]
        logger.warning(f"Text truncated to {max_chars} chars")
    
    try:
        client = Groq(api_key=GROQ_API_KEY)
        
        logger.info(f"→ Sending {len(raw_text)} chars to Groq ({GROQ_MODEL})...")
        
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.1,  # Low temperature for consistent extraction
            response_format={"type": "json_object"},  # Force JSON output
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract all information from this text:\n\n{raw_text}"}
            ],
            timeout=httpx.Timeout(connect=10.0, read=timeout_seconds, write=30.0, pool=10.0),
        )
        
        content = response.choices[0].message.content or "{}"
        logger.info(f"✓ Received response from Groq ({len(content)} chars)")
        
        # Parse JSON
        data = _extract_json_safely(content)
        return data
    
    except httpx.TimeoutException:
        logger.error("Groq API timeout")
        raise HTTPException(status_code=504, detail="AI processing timeout. Try a smaller PDF or reduce pages.")
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        raise HTTPException(status_code=500, detail=f"AI processing failed: {str(e)}")

def _extract_json_safely(text: str) -> Dict[str, Any]:
    """Extract JSON from text that might contain markdown or extra content"""
    # Try 1: Direct parse
    try:
        return json.loads(text)
    except:
        pass
    
    # Try 2: Extract from code block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    
    # Try 3: Find largest JSON object
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end+1])
        except:
            pass
    
    logger.warning("Could not extract valid JSON from Groq response")
    return {}

# --- Data Normalization ---
NUM_PATTERN = re.compile(r'([-+]?\d+(?:[.,]\d+)?)')

def normalize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize LLM output to ensure consistent format
    - Convert string numbers to floats
    - Handle unit extraction
    - Clean up malformed data
    """
    if not isinstance(data, dict):
        return {}
    
    # Normalize nutrition values
    nutrition = data.get("nutrition")
    if isinstance(nutrition, dict):
        numeric_fields = [
            "energy_kj", "energy_kcal", "fat_g", "saturated_fat_g",
            "carbohydrate_g", "sugars_g", "protein_g", "fiber_g",
            "salt_g", "sodium_g"
        ]
        for field in numeric_fields:
            nutrition[field] = _extract_number(nutrition.get(field))
    
    # Normalize net_quantity
    net_qty = data.get("net_quantity")
    if isinstance(net_qty, str):
        amount = _extract_number(net_qty)
        unit = _extract_unit(net_qty)
        data["net_quantity"] = {"amount": amount, "unit": unit}
    
    return data

def _extract_number(value) -> Optional[float]:
    """Extract numeric value from various formats"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove units and extract number
        match = NUM_PATTERN.search(value)
        if match:
            num_str = match.group(1).replace(',', '.')
            try:
                return float(num_str)
            except:
                return None
    return None

def _extract_unit(value: str) -> Optional[str]:
    """Extract unit from string like '500 g' or '1.5L'"""
    if not isinstance(value, str):
        return None
    
    # Common units
    units = ['kg', 'g', 'l', 'ml', 'cl', 'oz', 'lb', 'db', 'pcs']
    value_lower = value.lower()
    
    for unit in units:
        if unit in value_lower:
            return unit
    
    return None

# --- API Endpoints ---
@app.get("/")
def root():
    """Root endpoint with API information"""
    return {
        "message": "PDF Allergen & Nutrition Extractor API",
        "version": "2.0.0",
        "endpoints": {
            "extract": "POST /api/extract (upload PDF)",
            "health": "GET /api/health"
        },
        "documentation": "/docs"
    }

@app.get("/api/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model": GROQ_MODEL,
        "api_key_configured": bool(GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key"),
        "ocr_available": bool(pytesseract.get_tesseract_version()),
        "max_pdf_size_mb": MAX_PDF_SIZE_MB
    }

@app.post("/api/extract", response_model=ExtractResponse)
async def extract_from_pdf(file: UploadFile = File(...)):
    """
    Extract allergen and nutritional information from PDF
    
    Process:
    1. Validate PDF file
    2. Extract text (direct or OCR)
    3. Send to Groq AI for analysis
    4. Return structured JSON
    """
    # Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Only PDF files are accepted."
        )
    
    # Read file
    file_content = await file.read()
    file_size_mb = len(file_content) / (1024 * 1024)
    
    # Check file size
    if file_size_mb > MAX_PDF_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {file_size_mb:.1f}MB. Maximum size is {MAX_PDF_SIZE_MB}MB."
        )
    
    logger.info(f"📄 Processing PDF: {file.filename} ({file_size_mb:.2f}MB)")
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        tmp_file.write(file_content)
        pdf_path = tmp_file.name
    
    try:
        # Step 1: Extract text from PDF
        extracted_text, extraction_mode = extract_text_from_pdf(pdf_path)
        
        if not extracted_text or len(extracted_text.strip()) < 10:
            logger.warning("No text could be extracted from PDF")
            return ExtractResponse(
                allergens=[],
                nutrition=None,
                meta={
                    "mode": "empty",
                    "error": "No text found in PDF",
                    "filename": file.filename
                }
            )
        
        # Step 2: Send to Groq for AI analysis
        raw_data = extract_with_groq(extracted_text, timeout_seconds=60)
        
        # Step 3: Normalize data
        normalized_data = normalize_data(raw_data)
        
        # Step 4: Validate with Pydantic
        try:
            result = ExtractResponse.model_validate(normalized_data)
        except Exception as validation_error:
            logger.error(f"Validation error: {validation_error}")
            # Return partial data on validation failure
            result = ExtractResponse(
                allergens=normalized_data.get("allergens", []),
                nutrition=normalized_data.get("nutrition"),
                meta={"validation_error": str(validation_error)}
            )
        
        # Add metadata
        result.meta.update({
            "mode": extraction_mode,
            "text_length": len(extracted_text),
            "model": GROQ_MODEL,
            "filename": file.filename,
            "file_size_mb": round(file_size_mb, 2)
        })
        
        logger.info(f"✓ Successfully processed {file.filename}")
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error processing {file.filename}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process PDF: {str(e)}"
        )
    finally:
        # Clean up temporary file
        try:
            os.remove(pdf_path)
        except:
            pass

# --- Run Server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )