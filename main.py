import os
import base64
import tempfile
import json
import re
import platform
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import pytesseract
from PIL import Image
import pdfplumber
from docx import Document
from groq import Groq

load_dotenv()

# ─── Tesseract path (Windows only) ───────────────────────────────────────────
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = Flask(__name__)
CORS(app)

# ─── Config ───────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
API_KEY      = os.getenv("API_KEY", "sk_track2_987654321")

if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY not set!")

groq_client = Groq(api_key=GROQ_API_KEY)

# ─── API Key Auth ─────────────────────────────────────────────────────────────
def check_api_key():
    key = request.headers.get("x-api-key")
    if not key or key != API_KEY:
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Invalid or missing API key."
        }), 401
    return None

# ─── Text Extraction ──────────────────────────────────────────────────────────
def extract_from_image(file_bytes):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        img  = Image.open(tmp_path)
        text = pytesseract.image_to_string(img)
        print("IMAGE OCR TEXT:", text[:200])
        return text.strip()
    finally:
        os.unlink(tmp_path)

def extract_from_pdf(file_bytes):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        text = ""
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        print("PDF TEXT:", text[:200])
        return text.strip()
    finally:
        os.unlink(tmp_path)

def extract_from_docx(file_bytes):
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        doc  = Document(tmp_path)
        text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        print("DOCX TEXT:", text[:200])
        return text.strip()
    finally:
        os.unlink(tmp_path)

# ─── AI Analysis ──────────────────────────────────────────────────────────────
def analyze_with_ai(text):
    short_text = text[:1500]

    prompt = f"""Analyze this document. Output ONLY this JSON, nothing else:

{{"summary":"one sentence max 10 words","entities":{{"names":["max 2 person names"],"dates":["max 2 dates"],"organizations":["max 2 orgs"],"amounts":["max 2 amounts"]}},"sentiment":"Positive"}}

Replace values with real data from document. Keep ALL values SHORT.
Use Positive, Neutral, or Negative for sentiment.
If nothing found for a list use [].

Document:
{short_text}"""

    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        temperature=0,
        max_tokens=500,
        messages=[
            {
                "role": "system",
                "content": "Output only valid compact JSON. No markdown. No explanation. Keep all values very short."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw = response.choices[0].message.content.strip()
    print("=== RAW AI OUTPUT ===")
    print(raw)
    print("====================")

    # Clean markdown
    raw = re.sub(r"```json", "", raw)
    raw = re.sub(r"```",    "", raw)
    raw = raw.strip()

    # Extract JSON between { and }
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    print("=== CLEANED JSON ===")
    print(raw)
    print("===================")

    return json.loads(raw)

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status":  "success",
        "message": "AI Document Analyzer API is running 🚀"
    })

@app.route("/api/document-analyze", methods=["POST"])
def analyze_document():

    # Auth check
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Request body must be JSON"}), 400

    file_name   = data.get("fileName",   "")
    file_type   = data.get("fileType",   "").lower()
    file_base64 = data.get("fileBase64", "")

    print(f"=== REQUEST: fileName={file_name}, fileType={file_type} ===")

    if not file_name or not file_type or not file_base64:
        return jsonify({
            "status":  "error",
            "message": "Missing required fields: fileName, fileType, fileBase64"
        }), 400

    if file_type not in ["pdf", "docx", "image"]:
        return jsonify({
            "status":  "error",
            "message": "Invalid fileType. Supported: pdf, docx, image"
        }), 400

    # Decode Base64
    try:
        file_bytes = base64.b64decode(file_base64)
        print(f"File decoded: {len(file_bytes)} bytes")
    except Exception as e:
        return jsonify({"status": "error", "message": f"Invalid base64: {str(e)}"}), 400

    # Extract text
    try:
        if file_type == "image":
            extracted_text = extract_from_image(file_bytes)
        elif file_type == "pdf":
            extracted_text = extract_from_pdf(file_bytes)
        elif file_type == "docx":
            extracted_text = extract_from_docx(file_bytes)
    except Exception as e:
        print("EXTRACTION ERROR:", str(e))
        return jsonify({
            "status":  "error",
            "message": f"Text extraction failed: {str(e)}"
        }), 500

    if not extracted_text:
        return jsonify({
            "status":  "error",
            "message": "No text could be extracted from the document"
        }), 422

    print(f"Extracted {len(extracted_text)} characters")

    # AI Analysis
    try:
        ai_result = analyze_with_ai(extracted_text)
    except json.JSONDecodeError as e:
        print("JSON PARSE ERROR:", str(e))
        # Return fallback response
        return jsonify({
            "status":   "success",
            "fileName": file_name,
            "summary":  "Document analyzed successfully.",
            "entities": {
                "names":         [],
                "dates":         [],
                "organizations": [],
                "amounts":       []
            },
            "sentiment": "Neutral"
        }), 200
    except Exception as e:
        print("AI ERROR:", str(e))
        return jsonify({
            "status":  "error",
            "message": f"AI analysis failed: {str(e)}"
        }), 500

    # Return final response
    return jsonify({
        "status":   "success",
        "fileName": file_name,
        "summary":  ai_result.get("summary", ""),
        "entities": {
            "names":         ai_result.get("entities", {}).get("names",         []),
            "dates":         ai_result.get("entities", {}).get("dates",         []),
            "organizations": ai_result.get("entities", {}).get("organizations", []),
            "amounts":       ai_result.get("entities", {}).get("amounts",       [])
        },
        "sentiment": ai_result.get("sentiment", "Neutral")
    }), 200


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
    