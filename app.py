"""
🎯 MULTI-TENANT UPI VERIFICATION SYSTEM - USAGE GUIDE

═══════════════════════════════════════════════════════════════════════════════
📋 YOUR WORKFLOW:
═══════════════════════════════════════════════════════════════════════════════

1️⃣ PREPARE TENANT DATA (You do this beforehand):
   - Extract UPI transaction details from multiple tenant screenshots
   - Create a tenant_data_array with the required format

2️⃣ PROCESS BANK STATEMENT:
   - Upload landlord's bank statement (PDF/Image)
   - System finds matches for ALL tenants at once

3️⃣ GET VERIFICATION RESULTS:
   - Receive array of verification results
   - Each tenant gets: VERIFIED, PARTIAL, NO_MATCH, or ERROR status

═══════════════════════════════════════════════════════════════════════════════
💻 CODE EXAMPLES:
═══════════════════════════════════════════════════════════════════════════════

## METHOD 1: Helper Functions (Recommended)
tenant_data = []
tenant_data.append(create_tenant_data_entry("123456789012", "15000", "2024-01-15", 0.9, "PhonePe screenshot"))
tenant_data.append(create_tenant_data_entry("987654321098", "12000", "2024-01-16", 0.8, "Google Pay receipt"))

# Validate format
is_valid, message = validate_tenant_data_array(tenant_data)
if is_valid:
    results = extract_upi_data_from_bank_statement_multi("/path/to/statement.pdf", tenant_data)
    verification = verify_utr_match_multi(tenant_data, results)

## METHOD 2: Direct Array Creation  
tenant_data = [
    {
        "utr_number": "240115123456",
        "amount": "15000", 
        "date": "2024-01-15",
        "confidence_score": 0.9,
        "extraction_notes": "Clear UTR from tenant 1 PhonePe screenshot"
    },
    {
        "utr_number": "240116789012", 
        "amount": "12000",
        "date": "2024-01-16",
        "confidence_score": 0.8,
        "extraction_notes": "UTR from tenant 2 Google Pay receipt"
    }
]

## METHOD 3: API Call (POST to /upload-multi)
# Send: landlord_statement file + tenant_data JSON
# Receive: Complete verification results

═══════════════════════════════════════════════════════════════════════════════
📊 EXPECTED OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════════════════════

[
    {
        "tenant_id": 1,
        "match_status": "VERIFIED",
        "utr_match": true,
        "amount_match": true, 
        "date_match": true,
        "overall_confidence": 0.85,
        "tenant_utr": "240115123456",
        "landlord_utr": "240115123456",
        "verification_summary": "UTR: ✅, Amount: ✅, Date: ✅"
    },
    {
        "tenant_id": 2,
        "match_status": "PARTIAL",
        "utr_match": false,
        "amount_match": true,
        "date_match": true, 
        "overall_confidence": 0.45,
        "verification_summary": "UTR: ❌, Amount: ✅, Date: ✅"
    }
]

═══════════════════════════════════════════════════════════════════════════════
🔧 KEY FUNCTIONS:
═══════════════════════════════════════════════════════════════════════════════

✅ extract_upi_data_from_bank_statement_multi(file_path, tenant_data_array)
✅ verify_utr_match_multi(tenant_data_array, landlord_results)  
✅ create_tenant_data_entry(utr, amount, date, confidence, notes)
✅ validate_tenant_data_array(tenant_data_array)
✅ example_your_workflow() - See complete example

═══════════════════════════════════════════════════════════════════════════════
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import json
import uuid
import re
import base64
from werkzeug.utils import secure_filename
import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part
import tempfile
import os
from config import config

app = Flask(__name__)

# Load configuration based on environment
config_name = os.environ.get('FLASK_ENV', 'default')
app.config.from_object(config[config_name])

# Configuration from config.py
ALLOWED_EXTENSIONS = app.config['ALLOWED_EXTENSIONS']
ALLOWED_STATEMENT_EXTENSIONS = app.config.get('ALLOWED_STATEMENT_EXTENSIONS', {'png', 'jpg', 'jpeg', 'webp', 'heic', 'pdf'})
MAX_FILE_SIZE = app.config['MAX_CONTENT_LENGTH']
PROJECT_ID = app.config['GCP_PROJECT_ID']
LOCATION = app.config['GCP_LOCATION']

# Performance tracking for JSON parsing strategies
parsing_stats = {
    "direct": 0,
    "markdown": 0,
    "bracket": 0,
    "failed": 0
}

# Initialize Vertex AI with error handling
model = None
try:
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID not found in environment variables")
    
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.5-flash-lite")  # Supports direct PDF processing
    print(f"✅ Successfully connected to Vertex AI - Project: {PROJECT_ID}, Location: {LOCATION}")
except Exception as e:
    print(f"❌ Failed to initialize Vertex AI: {str(e)}")
    print("Please check your Google Cloud credentials and project settings in .env file")
    print("Make sure you have:")
    print("1. Set GCP_PROJECT_ID in .env")
    print("2. Configured GOOGLE_APPLICATION_CREDENTIALS or used 'gcloud auth application-default login'")
    print("3. Enabled Vertex AI API in your Google Cloud project")

def allowed_file(filename):
    """Check if uploaded file has allowed extension (for tenant - images only)"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_statement_file(filename):
    """Check if uploaded statement file has allowed extension (including PDF)"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_STATEMENT_EXTENSIONS

def parse_gemini_json_response(response_text, context="UPI extraction"):
    """
    Parse Gemini JSON response with multiple strategies
    Optimized for response_mime_type="application/json" but with fallbacks
    """
    response_text = response_text.strip()
    print(f"DEBUG: {context} - Raw response length: {len(response_text)}")
    print(f"DEBUG: {context} - Raw response: {response_text}")

    # Strategy 1: Direct JSON parsing (should work with response_mime_type)
    try:
        extracted_data = json.loads(response_text)
        print(f"DEBUG: ✅ {context} - Strategy 1 (Direct JSON) succeeded")
        parsing_stats["direct"] += 1
        return extracted_data, "direct"
    except json.JSONDecodeError as e:
        print(f"DEBUG: ⚠️ {context} - Strategy 1 failed: {e}")

    # Strategy 2: Markdown code block extraction
    json_pattern = r'``````'
    match = re.search(json_pattern, response_text, re.DOTALL)
    if match:
        try:
            json_text = match.group(1).strip()
            extracted_data = json.loads(json_text)
            print(f"DEBUG: ✅ {context} - Strategy 2 (Markdown) succeeded")
            parsing_stats["markdown"] += 1
            return extracted_data, "markdown"
        except json.JSONDecodeError:
            print(f"DEBUG: ⚠️ {context} - Strategy 2 found pattern but parsing failed")
    else:
        print(f"DEBUG: ⚠️ {context} - Strategy 2 no code block found")

    # Strategy 3: Bracket-based extraction
    try:
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_text = response_text[start_idx:end_idx+1]
            extracted_data = json.loads(json_text)
            print(f"DEBUG: ✅ {context} - Strategy 3 (Bracket extraction) succeeded")
            parsing_stats["bracket"] += 1
            return extracted_data, "bracket"
        else:
            print(f"DEBUG: ⚠️ {context} - Strategy 3 no valid brackets found")
    except json.JSONDecodeError as e:
        print(f"DEBUG: ⚠️ {context} - Strategy 3 failed: {e}")

    # All strategies failed
    print(f"DEBUG: ❌ {context} - All parsing strategies failed")
    parsing_stats["failed"] += 1
    return None, "failed"

def extract_upi_data_from_file(image_path):
    """Extract UPI transaction data using Gemini from tenant UPI screenshot (single transaction)"""
    
    # Check if model is initialized
    if model is None:
        return {
            "error": "Gemini API not initialized. Check your Google Cloud configuration.",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "API initialization failed"
        }
    
    try:
        # Read and process the image file
        with open(image_path, 'rb') as image_file:
            image_bytes = image_file.read()
            
        # Create image part from bytes
        image_part = Part.from_data(
            data=image_bytes,
            mime_type="image/jpeg"
        )
        
        # Enhanced prompt for UPI data extraction (optimized for JSON response)
        prompt = """
        Analyze this UPI transaction screenshot and extract the following information.
        
        REQUIRED FIELDS:
        - utr_number: UTR/Reference number (look for labels like "UTR:", "Ref No:", "Transaction ID:")
        - amount: Transaction amount (numerical value only)
        - date: Transaction date (YYYY-MM-DD format)
        
        IMPORTANT INSTRUCTIONS:
        1. Focus specifically on finding the UTR number - it's typically 12 digits
        2. If UTR is not clearly visible, set confidence_score to low (< 0.5)
        3. Extract exact text as shown in the image
        4. Return ONLY valid, clearly visible data
        5. If a field is not visible, return empty string ""
        
        Return this JSON structure:
        {
            "utr_number": "string",
            "amount": "string",
            "date": "string",
            "confidence_score": 0.8,
            "extraction_notes": "any important observations"
        }
        """
        
        # Generate response
        response = model.generate_content(
            [image_part, prompt],
            generation_config={
                "max_output_tokens": 2048,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }
        )
        
        # 🔍 LOG RAW RESPONSE - EXACTLY what Gemini returns
        print(f"\n" + "="*80)
        print(f"🔍 RAW GEMINI RESPONSE (UPI extraction):")
        print(f"Response type: {type(response.text)}")
        print(f"Response length: {len(response.text)} characters")
        print(f"Raw response content:")
        print(f"'{response.text}'")
        print(f"Raw response repr:")
        print(repr(response.text))
        print(f"="*80 + "\n")
        
        # Optimized JSON parsing using utility function
        extracted_data, parse_method = parse_gemini_json_response(response.text, "UPI extraction")
        
        if extracted_data is None:
            return {
                "error": f"Failed to parse Gemini response. Method tried: {parse_method}. Raw response: {response.text[:200]}...",
                "confidence_score": 0.0,
                "utr_number": "",
                "amount": "",
                "date": "",
                "extraction_notes": f"JSON parsing failed using response_mime_type - {parse_method}"
            }
        
        # Ensure all required fields exist with default values
        default_data = {
            "utr_number": "",
            "amount": "",
            "date": "",
            "confidence_score": 0.0,
            "extraction_notes": ""
        }
        
        # Merge extracted data with defaults and ensure proper types
        for key in default_data:
            if key not in extracted_data:
                extracted_data[key] = default_data[key]
            elif key == "confidence_score":
                # Ensure confidence_score is a float between 0 and 1
                try:
                    score = float(extracted_data[key])
                    extracted_data[key] = max(0.0, min(1.0, score))
                except (ValueError, TypeError):
                    extracted_data[key] = 0.0
            elif isinstance(extracted_data[key], (int, float)) and key != "confidence_score":
                # Convert numeric values to strings for consistency
                extracted_data[key] = str(extracted_data[key])
        
        print(f"DEBUG: Final processed data: {extracted_data}")
        return extracted_data
        
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse API response as JSON: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "JSON parsing failed"
        }
    except Exception as e:
        return {
            "error": f"OCR extraction failed: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": f"Extraction error: {str(e)}"
        }

def extract_upi_data_from_bank_statement_direct(file_path, tenant_details):
    """
    ✨ NEW: Direct PDF/Image processing - handles both formats natively
    Extract UPI transaction data from landlord bank statement (PDF or image) using tenant details for matching
    """
    
    # Check if model is initialized
    if model is None:
        return {
            "error": "Gemini API not initialized. Check your Google Cloud configuration.",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "API initialization failed"
        }
    
    try:
        # Determine file type and create appropriate Part
        file_extension = os.path.splitext(file_path)[1].lower()
        
        with open(file_path, 'rb') as file:
            file_bytes = file.read()
        
        if file_extension == '.pdf':
            print("DEBUG: Processing PDF bank statement directly with Gemini")
            # Create PDF part for direct processing
            document_part = Part.from_data(
                mime_type="application/pdf",
                data=file_bytes
            )
        else:
            print("DEBUG: Processing image bank statement")
            # Create image part
            document_part = Part.from_data(
                mime_type="image/jpeg",
                data=file_bytes
            )
        
        # Get tenant transaction details for matching
        tenant_amount = tenant_details.get('amount', '')
        tenant_date = tenant_details.get('date', '')
        tenant_utr = tenant_details.get('utr_number', '')
        
        # Enhanced prompt specifically for bank statement (PDF or image) with multiple transactions
        prompt = f"""
        You are analyzing a BANK STATEMENT {'PDF document' if file_extension == '.pdf' else 'image'} that shows MULTIPLE transactions in a list/table format.

        BANK STATEMENT FORMAT:
        - {'PDF document contains' if file_extension == '.pdf' else 'Image contains'} multiple transactions displayed in rows/list
        - Each transaction shows: Date, Description (with UPI details), Amount, Reference/UTR number
        - Amounts may have +/- indicators for credit/debit
        - UTR numbers are typically 10-16 digit numbers
        - Transaction descriptions contain detailed UPI payment information
        - {'Search through ALL pages of the PDF document' if file_extension == '.pdf' else 'Search through the entire image'}

        SPECIFIC TRANSACTION TO FIND:
        Find the transaction that matches these tenant payment details:
        - Amount: {tenant_amount} INR
        - Date: {tenant_date}
        - UTR/Reference number: {tenant_utr} (if provided)

        SEARCH STRATEGY:
        1. {'Scan through ALL pages and look through each' if file_extension == '.pdf' else 'Look through each'} transaction row
        2. Match the amount ({tenant_amount}) exactly (ignore +/- signs)
        3. Match the date ({tenant_date}) exactly
        4. Match the UTR/Reference number ({tenant_utr}) exactly if provided
        5. Extract the UTR/Reference number from that specific matching row

        IMPORTANT INSTRUCTIONS:
        - Only extract from the ONE transaction that matches all criteria
        - If found, set confidence_score high (0.8-1.0)
        - If no exact match found, set confidence_score low (0.0-0.3) and explain why
        - Focus on the UTR number from the matching transaction row
        - DO NOT extract from random transactions
        - If multiple transactions match, choose the one closest to the given date
        - If no matching transaction is found, return empty strings for all fields
        - {'Specify which page the transaction was found on if applicable' if file_extension == '.pdf' else 'Confirm the transaction location in the image'}

        Return this JSON structure:
        {{
            "utr_number": "UTR from the matching transaction",
            "amount": "amount from the matching transaction",
            "date": "date from the matching transaction (YYYY-MM-DD)",
            "confidence_score": 0.8,
            "extraction_notes": "Details about which transaction was matched{'and page number' if file_extension == '.pdf' else ''}"
        }}
        """
        
        # Generate response using native PDF/image processing
        response = model.generate_content(
            [document_part, prompt],
            generation_config={
                "max_output_tokens": 2048,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }
        )
        
        # 🔍 LOG RAW RESPONSE - EXACTLY what Gemini returns
        print(f"\n" + "="*80)
        print(f"🔍 RAW GEMINI RESPONSE (Bank statement {'PDF' if file_extension == '.pdf' else 'image'}):")
        print(f"Response type: {type(response.text)}")
        print(f"Response length: {len(response.text)} characters")
        print(f"Raw response content:")
        print(f"'{response.text}'")
        print(f"Raw response repr:")
        print(repr(response.text))
        print(f"="*80 + "\n")
        
        # Optimized JSON parsing using utility function
        extracted_data, parse_method = parse_gemini_json_response(response.text, f"Bank statement ({'PDF' if file_extension == '.pdf' else 'image'})")
        
        if extracted_data is None:
            return {
                "error": f"Failed to parse bank statement response. Method: {parse_method}. Raw response: {response.text[:200]}...",
                "confidence_score": 0.0,
                "utr_number": "",
                "amount": "",
                "date": "",
                "extraction_notes": "JSON parsing failed - invalid format"
            }
        
        # Ensure all required fields exist with default values
        default_data = {
            "utr_number": "",
            "amount": "",
            "date": "",
            "confidence_score": 0.0,
            "extraction_notes": ""
        }
        
        # Merge extracted data with defaults and ensure proper types
        for key in default_data:
            if key not in extracted_data:
                extracted_data[key] = default_data[key]
            elif key == "confidence_score":
                # Ensure confidence_score is a float between 0 and 1
                try:
                    score = float(extracted_data[key])
                    extracted_data[key] = max(0.0, min(1.0, score))
                except (ValueError, TypeError):
                    extracted_data[key] = 0.0
            elif isinstance(extracted_data[key], (int, float)) and key != "confidence_score":
                # Convert numeric values to strings for consistency
                extracted_data[key] = str(extracted_data[key])
        
        print(f"DEBUG: Final bank statement processed data: {extracted_data}")
        return extracted_data
        
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse bank statement response: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "JSON parsing failed"
        }
    except Exception as e:
        return {
            "error": f"Bank statement extraction failed: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": f"Extraction error: {str(e)}"
        }

def extract_upi_data_from_bank_statement_multi(file_path, tenant_data_array):
    """
    🚀 NEW: Multi-tenant bank statement processing
    Extract and match multiple tenant transactions from bank statement (PDF or image)
    
    Args:
        file_path: Path to bank statement file (PDF or image)
        tenant_data_array: List of tenant transaction objects in format:
                          [{"utr_number": "...", "amount": "...", "date": "...", ...}, ...]
    
    Returns:
        List of matching results for each tenant in the same order as input
    """
    
    # Check if model is initialized
    if model is None:
        error_response = {
            "error": "Gemini API not initialized. Check your Google Cloud configuration.",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "API initialization failed"
        }
        return [error_response] * len(tenant_data_array)
    
    # Validate input
    if not tenant_data_array or not isinstance(tenant_data_array, list):
        error_response = {
            "error": "Invalid tenant data array provided",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "No tenant data provided"
        }
        return [error_response]
    
    try:
        # Determine file type and create appropriate Part
        file_extension = os.path.splitext(file_path)[1].lower()
        
        with open(file_path, 'rb') as file:
            file_bytes = file.read()
        
        if file_extension == '.pdf':
            print(f"DEBUG: Processing PDF bank statement with {len(tenant_data_array)} tenant records")
            document_part = Part.from_data(
                mime_type="application/pdf",
                data=file_bytes
            )
        else:
            print(f"DEBUG: Processing image bank statement with {len(tenant_data_array)} tenant records")
            document_part = Part.from_data(
                mime_type="image/jpeg",
                data=file_bytes
            )
        
        # Build tenant details for prompt
        tenant_search_list = []
        for i, tenant in enumerate(tenant_data_array):
            tenant_info = f"""
        TENANT {i+1}:
        - Amount: {tenant.get('amount', '')} INR
        - Date: {tenant.get('date', '')}
        - UTR/Reference: {tenant.get('utr_number', '')}
        - Tenant ID: {i+1}"""
            tenant_search_list.append(tenant_info)
        
        tenant_details_text = "\n".join(tenant_search_list)
        
        # Enhanced multi-tenant prompt
        prompt = f"""
        You are analyzing a BANK STATEMENT that shows MULTIPLE transactions.
        
        I need you to find matches for {len(tenant_data_array)} different tenant payments in this bank statement.
        
        TENANT PAYMENT DETAILS TO FIND:
        {tenant_details_text}
        
        BANK STATEMENT FORMAT:
        - Transactions are displayed in rows/lines
        - Each transaction shows: Date, Description (UPI details), Amount, UTR/Reference number
        - Amounts may have +/- indicators for credit/debit
        - UTR numbers are typically 12-digit numbers
        - {"Multiple pages may be present" if file_extension == '.pdf' else "All transactions are on this image"}
        
        SEARCH INSTRUCTIONS:
        1. Look through ALL transactions in the bank statement
        2. For each tenant, find the transaction that matches their amount, date, and UTR exactly
        3. If exact match found, extract the UTR from that transaction row
        4. If no exact match, try partial matching (amount + date only)
        5. Set confidence_score based on match quality:
           - 0.9-1.0: Exact match (amount + date + UTR)
           - 0.7-0.8: Strong match (amount + date, UTR found)
           - 0.4-0.6: Partial match (amount matches, date close)
           - 0.0-0.3: No clear match found
        
        IMPORTANT:
        - Return results for ALL {len(tenant_data_array)} tenants in the SAME ORDER as provided
        - If a tenant has no match, return empty strings but still include their entry
        - {"Specify page number if PDF has multiple pages" if file_extension == '.pdf' else "Specify location in image"}
        - Include processing time estimate
        
        Return this JSON structure as an ARRAY:
        [
            {{
                "tenant_id": 1,
                "utr_number": "UTR from matching transaction or empty string",
                "amount": "amount from matching transaction or empty string", 
                "date": "date from matching transaction (YYYY-MM-DD) or empty string",
                "confidence_score": 0.8,
                "extraction_notes": "Details about match quality{'and page number' if file_extension == '.pdf' else ''}",
                "processing_time_seconds": "estimated time for this tenant"
            }},
            {{
                "tenant_id": 2,
                "utr_number": "...",
                "amount": "...",
                "date": "...",
                "confidence_score": 0.6,
                "extraction_notes": "...",
                "processing_time_seconds": "..."
            }}
            // ... continue for all {len(tenant_data_array)} tenants
        ]
        """
        
        # Generate response using native PDF/image processing
        response = model.generate_content(
            [document_part, prompt],
            generation_config={
                "max_output_tokens": 4096,  # Increased for multiple results
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }
        )
        
        # 🔍 LOG RAW RESPONSE for multi-tenant processing
        print(f"\n" + "="*80)
        print(f"🔍 RAW GEMINI RESPONSE (Multi-tenant bank statement):")
        print(f"Response type: {type(response.text)}")
        print(f"Response length: {len(response.text)} characters")
        print(f"Raw response content:")
        print(f"'{response.text}'")
        print(f"Raw response repr:")
        print(repr(response.text))
        print(f"="*80 + "\n")
        
        # Parse the response - expecting an array
        extracted_data, parse_method = parse_gemini_json_response(response.text, "Multi-tenant bank statement")
        
        if extracted_data is None:
            error_response = {
                "error": f"Failed to parse multi-tenant response. Method: {parse_method}",
                "confidence_score": 0.0,
                "utr_number": "",
                "amount": "",
                "date": "",
                "extraction_notes": "JSON parsing failed"
            }
            return [error_response] * len(tenant_data_array)
        
        # Ensure we have an array response
        if not isinstance(extracted_data, list):
            print(f"DEBUG: Expected array but got {type(extracted_data)}, converting...")
            # If single object returned, wrap in array
            if isinstance(extracted_data, dict):
                extracted_data = [extracted_data]
            else:
                error_response = {
                    "error": "Invalid response format - expected array",
                    "confidence_score": 0.0,
                    "utr_number": "",
                    "amount": "",
                    "date": "",
                    "extraction_notes": "Response format error"
                }
                return [error_response] * len(tenant_data_array)
        
        # Process each tenant result
        processed_results = []
        for i, result in enumerate(extracted_data):
            # Ensure required fields exist with defaults
            default_result = {
                "tenant_id": i + 1,
                "utr_number": "",
                "amount": "",
                "date": "",
                "confidence_score": 0.0,
                "extraction_notes": ""
            }
            
            # Merge with extracted data
            for key in default_result:
                if key not in result:
                    result[key] = default_result[key]
                elif key == "confidence_score":
                    try:
                        score = float(result[key])
                        result[key] = max(0.0, min(1.0, score))
                    except (ValueError, TypeError):
                        result[key] = 0.0
                elif isinstance(result[key], (int, float)) and key != "confidence_score":
                    result[key] = str(result[key])
            
            # Log processing time if available
            if 'processing_time_seconds' in result:
                processing_time = result.get('processing_time_seconds', 'N/A')
                print(f"🕒 Tenant {i+1} processing time: {processing_time} seconds")
                del result['processing_time_seconds']  # Remove from client response
            
            processed_results.append(result)
        
        # Ensure we have results for all tenants (pad if necessary)
        while len(processed_results) < len(tenant_data_array):
            missing_tenant_id = len(processed_results) + 1
            processed_results.append({
                "tenant_id": missing_tenant_id,
                "utr_number": "",
                "amount": "",
                "date": "",
                "confidence_score": 0.0,
                "extraction_notes": f"No match found for tenant {missing_tenant_id}"
            })
        
        print(f"DEBUG: Processed {len(processed_results)} tenant results")
        return processed_results
        
    except json.JSONDecodeError as e:
        error_response = {
            "error": f"Failed to parse multi-tenant bank statement response: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": "JSON parsing failed"
        }
        return [error_response] * len(tenant_data_array)
    except Exception as e:
        error_response = {
            "error": f"Multi-tenant bank statement extraction failed: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "date": "",
            "extraction_notes": f"Extraction error: {str(e)}"
        }
        return [error_response] * len(tenant_data_array)

def verify_utr_match(tenant_data, landlord_data):
    """Compare UTR numbers and validate transaction match"""
    
    print("DEBUG: Tenant data:", tenant_data)
    print("DEBUG: Landlord data:", landlord_data)

    tenant_utr = (tenant_data.get('utr_number') or '').strip()
    landlord_utr = (landlord_data.get('utr_number') or '').strip()
    
    # Basic UTR validation
    def is_valid_utr(utr):
        return utr.isdigit() and len(utr) >= 10  # Allow 10+ digit UTRs
    
    tenant_valid = is_valid_utr(tenant_utr)
    landlord_valid = is_valid_utr(landlord_utr)
    
    match_found = tenant_utr == landlord_utr and tenant_valid and landlord_valid
    
    # Additional validation checks
    validation_checks = {
        'utr_match': match_found,
        'tenant_utr_valid': tenant_valid,
        'landlord_utr_valid': landlord_valid,
        'amount_match': tenant_data.get('amount') == landlord_data.get('amount'),
        'date_match': tenant_data.get('date') == landlord_data.get('date')
    }
    
    # Calculate overall confidence
    confidence_scores = [
        tenant_data.get('confidence_score', 0),
        landlord_data.get('confidence_score', 0)
    ]
    overall_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
    
    return {
        'verification_result': match_found,
        'tenant_utr': tenant_utr,
        'landlord_utr': landlord_utr,
        'validation_checks': validation_checks,
        'overall_confidence': overall_confidence,
        'tenant_data': tenant_data,
        'landlord_data': landlord_data
    }

def verify_utr_match_multi(tenant_data_array, landlord_results_array):
    """
    🚀 NEW: Multi-tenant verification
    Compare multiple tenant data with their corresponding bank statement matches
    
    Args:
        tenant_data_array: List of original tenant transaction data
        landlord_results_array: List of matching results from bank statement
    
    Returns:
        List of verification results for each tenant
    """
    
    try:
        verification_results = []
        
        # Ensure both arrays have the same length
        max_length = max(len(tenant_data_array), len(landlord_results_array))
        
        for i in range(max_length):
            # Get tenant data (or default if missing)
            tenant_data = tenant_data_array[i] if i < len(tenant_data_array) else {}
            
            # Get landlord result (or default if missing)  
            landlord_data = landlord_results_array[i] if i < len(landlord_results_array) else {}
            
            # Safely extract data with None handling
            tenant_utr = (tenant_data.get('utr_number') or '').strip()
            landlord_utr = (landlord_data.get('utr_number') or '').strip()
            
            tenant_amount = (tenant_data.get('amount') or '').strip()
            landlord_amount = (landlord_data.get('amount') or '').strip()
            
            tenant_date = (tenant_data.get('date') or '').strip()
            landlord_date = (landlord_data.get('date') or '').strip()
            
            # Get confidence scores
            tenant_confidence = tenant_data.get('confidence_score', 0.0)
            landlord_confidence = landlord_data.get('confidence_score', 0.0)
            
            # Ensure confidence scores are numbers
            if not isinstance(tenant_confidence, (int, float)):
                tenant_confidence = 0.0
            if not isinstance(landlord_confidence, (int, float)):
                landlord_confidence = 0.0
            
            print(f"DEBUG: Tenant {i+1} - Comparing UTRs: '{tenant_utr}' vs '{landlord_utr}'")
            print(f"DEBUG: Tenant {i+1} - Comparing amounts: '{tenant_amount}' vs '{landlord_amount}'")
            
            # UTR comparison
            utr_match = bool(tenant_utr and landlord_utr and tenant_utr == landlord_utr)
            
            # Amount comparison
            amount_match = False
            if tenant_amount and landlord_amount:
                # Remove currency symbols and normalize
                tenant_amt_clean = re.sub(r'[^\d.]', '', tenant_amount)
                landlord_amt_clean = re.sub(r'[^\d.]', '', landlord_amount)
                try:
                    tenant_float = float(tenant_amt_clean) if tenant_amt_clean else 0
                    landlord_float = float(landlord_amt_clean) if landlord_amt_clean else 0
                    amount_match = abs(tenant_float - landlord_float) < 0.01
                except ValueError:
                    amount_match = tenant_amount.lower() == landlord_amount.lower()
            
            # Date comparison
            date_match = bool(tenant_date and landlord_date and tenant_date == landlord_date)
            
            # Calculate overall confidence
            overall_confidence = (tenant_confidence + landlord_confidence) / 2
            if not utr_match:
                overall_confidence *= 0.5
            if not amount_match and tenant_amount and landlord_amount:
                overall_confidence *= 0.7
            
            # Create verification result for this tenant
            tenant_result = {
                'tenant_id': i + 1,
                'utr_match': utr_match,
                'amount_match': amount_match,
                'date_match': date_match,
                'overall_confidence': round(overall_confidence, 2),
                'tenant_utr': tenant_utr,
                'landlord_utr': landlord_utr,
                'tenant_amount': tenant_amount,
                'landlord_amount': landlord_amount,
                'tenant_date': tenant_date,
                'landlord_date': landlord_date,
                'match_status': 'VERIFIED' if utr_match and amount_match else 'PARTIAL' if (utr_match or amount_match) else 'NO_MATCH',
                'landlord_extraction_notes': landlord_data.get('extraction_notes', ''),
                'verification_summary': f"UTR: {'✅' if utr_match else '❌'}, Amount: {'✅' if amount_match else '❌'}, Date: {'✅' if date_match else '❌'}"
            }
            
            verification_results.append(tenant_result)
            
            print(f"DEBUG: Tenant {i+1} verification: {tenant_result['match_status']} (confidence: {tenant_result['overall_confidence']})")
        
        return verification_results
        
    except Exception as e:
        print(f"ERROR: Multi-tenant verification failed: {str(e)}")
        # Return error result for each tenant
        error_results = []
        for i in range(len(tenant_data_array)):
            error_results.append({
                'tenant_id': i + 1,
                'utr_match': False,
                'amount_match': False,
                'date_match': False,
                'overall_confidence': 0.0,
                'error': str(e),
                'match_status': 'ERROR'
            })
        return error_results
@app.route('/')
def index():
    """Main upload page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file upload and processing with direct PDF support"""
    
    print("DEBUG: Upload route called")
    print(f"DEBUG: Files in request: {list(request.files.keys())}")
    
    # Check if files are present
    if 'tenant_screenshot' not in request.files or 'landlord_screenshot' not in request.files:
        print("DEBUG: Missing files in request")
        flash('Both tenant and landlord screenshots are required!')
        return redirect(url_for('index'))
    
    tenant_file = request.files['tenant_screenshot']
    landlord_file = request.files['landlord_screenshot']
    
    print(f"DEBUG: Tenant file: {tenant_file.filename}")
    print(f"DEBUG: Landlord file: {landlord_file.filename}")
    
    # Validate files
    if tenant_file.filename == '' or landlord_file.filename == '':
        print("DEBUG: Empty filenames")
        flash('Please select both files!')
        return redirect(url_for('index'))
    
    # Updated validation - tenant must be image, landlord can be image or PDF
    if not allowed_file(tenant_file.filename):
        print(f"DEBUG: Invalid tenant file type")
        flash('Tenant screenshot must be PNG, JPG, JPEG, WEBP, or HEIC!')
        return redirect(url_for('index'))
        
    if not allowed_statement_file(landlord_file.filename):
        print(f"DEBUG: Invalid landlord file type")
        flash('Bank statement must be PNG, JPG, JPEG, WEBP, HEIC, or PDF!')
        return redirect(url_for('index'))
    
    # Check if Gemini API is initialized
    if model is None:
        print("DEBUG: Model is None")
        flash('Gemini API not available. Please check your Google Cloud configuration.')
        return redirect(url_for('index'))
    
    print("DEBUG: All validations passed, starting processing...")
    
    try:
        print("DEBUG: Starting file processing with temporary files...")
        
        # Save uploaded files to temporary files
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_tenant:
            tenant_file.save(temp_tenant.name)
            tenant_temp_path = temp_tenant.name
            
        # Handle different file types for landlord
        landlord_extension = os.path.splitext(landlord_file.filename)[1].lower()
        suffix = '.pdf' if landlord_extension == '.pdf' else '.jpg'
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_landlord:
            landlord_file.save(temp_landlord.name)
            landlord_temp_path = temp_landlord.name
            
        print(f"DEBUG: Saved temp files: {tenant_temp_path}, {landlord_temp_path}")
        
        try:
            # STEP 1: Process tenant UPI screenshot first (same as before)
            print("DEBUG: Processing tenant UPI screenshot...")
            tenant_data = extract_upi_data_from_file(tenant_temp_path)
            print(f"DEBUG: Tenant data extracted: {tenant_data}")
            
            # Check for tenant extraction errors
            if 'error' in tenant_data:
                error_msg = f"Tenant UPI screenshot extraction failed: {tenant_data['error']}"
                print(f"DEBUG: Tenant extraction error: {error_msg}")
                flash(error_msg)
                return redirect(url_for('index'))
            
            # STEP 2: Process landlord bank statement (PDF or image) using direct processing
            print("DEBUG: Processing landlord bank statement directly...")
            landlord_data = extract_upi_data_from_bank_statement_direct(landlord_temp_path, tenant_data)
            print(f"DEBUG: Landlord data extracted: {landlord_data}")
            
            # Check for landlord extraction errors
            if 'error' in landlord_data:
                error_msg = f"Landlord bank statement extraction failed: {landlord_data['error']}"
                print(f"DEBUG: Landlord extraction error: {error_msg}")
                flash(error_msg)
                return redirect(url_for('index'))
            
            print("DEBUG: Both extractions successful, verifying UTR match...")
            # Verify UTR match
            verification_result = verify_utr_match(tenant_data, landlord_data)
            
            print("DEBUG: UTR verification complete, preparing result...")
            # Add session info for display
            session_id = str(uuid.uuid4())
            verification_result['session_id'] = session_id
            verification_result['tenant_filename'] = secure_filename(tenant_file.filename)
            verification_result['landlord_filename'] = secure_filename(landlord_file.filename)
            
            print("DEBUG: Rendering result template...")
            return render_template('result.html', result=verification_result)
            
        finally:
            # Clean up temporary files
            try:
                os.unlink(tenant_temp_path)
                os.unlink(landlord_temp_path)
                print("DEBUG: Cleaned up temporary files")
            except Exception as cleanup_error:
                print(f"DEBUG: Error cleaning temp files: {cleanup_error}")
    
    except Exception as e:
        print(f"DEBUG: Exception caught: {str(e)}")
        print(f"DEBUG: Exception type: {type(e)}")
        import traceback
        print(f"DEBUG: Traceback: {traceback.format_exc()}")
        flash(f'Error processing files: {str(e)}')
        return redirect(url_for('index'))

@app.route('/api/verify', methods=['POST'])
def api_verify():
    """API endpoint for programmatic access with PDF support"""
    
    if 'tenant_screenshot' not in request.files or 'landlord_screenshot' not in request.files:
        return jsonify({'error': 'Both files required'}), 400
    
    # Check if Gemini API is initialized
    if model is None:
        return jsonify({'error': 'Gemini API not initialized. Check Google Cloud configuration.'}), 500
    
    try:
        tenant_file = request.files['tenant_screenshot']
        landlord_file = request.files['landlord_screenshot']
        
        # Updated validation for API
        if not allowed_file(tenant_file.filename):
            return jsonify({'error': 'Tenant file must be image format (PNG, JPG, JPEG, WEBP, HEIC)'}), 400
        
        if not allowed_statement_file(landlord_file.filename):
            return jsonify({'error': 'Bank statement must be image or PDF format'}), 400
        
        # Process files (same logic as web route)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_tenant:
            tenant_file.save(temp_tenant.name)
            tenant_temp_path = temp_tenant.name
            
        landlord_extension = os.path.splitext(landlord_file.filename)[1].lower()
        suffix = '.pdf' if landlord_extension == '.pdf' else '.jpg'
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_landlord:
            landlord_file.save(temp_landlord.name)
            landlord_temp_path = temp_landlord.name
        
        try:
            # STEP 1: Process tenant UPI screenshot first
            tenant_data = extract_upi_data_from_file(tenant_temp_path)
            
            # Check for tenant extraction errors
            if 'error' in tenant_data:
                return jsonify({
                    'error': 'Tenant UPI screenshot extraction failed',
                    'tenant_error': tenant_data.get('error')
                }), 422
            
            # STEP 2: Process landlord bank statement using direct processing
            landlord_data = extract_upi_data_from_bank_statement_direct(landlord_temp_path, tenant_data)
            
            # Check for landlord extraction errors
            if 'error' in landlord_data:
                return jsonify({
                    'error': 'Landlord bank statement extraction failed',
                    'landlord_error': landlord_data.get('error')
                }), 422
            
            verification_result = verify_utr_match(tenant_data, landlord_data)
            
            return jsonify(verification_result)
        
        finally:
            # Clean up temporary files
            try:
                os.unlink(tenant_temp_path)
                os.unlink(landlord_temp_path)
            except Exception as cleanup_error:
                print(f"API: Error cleaning temp files: {cleanup_error}")
    
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint with PDF support info"""
    total_requests = sum(parsing_stats.values())
    status = {
        'status': 'healthy',
        'gemini_api': 'connected' if model is not None else 'disconnected',
        'project_id': PROJECT_ID or 'not_set',
        'location': LOCATION,
        'response_mime_type': 'enabled',
        'pdf_support': 'native_processing',  # Updated to reflect native processing
        'parsing_performance': {
            'total_requests': total_requests,
            'direct_json_success_rate': f"{(parsing_stats['direct'] / max(total_requests, 1)) * 100:.1f}%",
            'fallback_usage': {
                'markdown': parsing_stats['markdown'],
                'bracket': parsing_stats['bracket'],
                'failed': parsing_stats['failed']
            }
        }
    }
    return jsonify(status)

@app.route('/upload-multi', methods=['POST'])
def upload_multi_tenant():
    """
    🚀 MULTI-TENANT PROCESSING ENDPOINT
    
    USE CASE: You have pre-extracted tenant data from multiple UPI screenshots
    and want to find matches in the landlord's bank statement
    
    INPUT:
    - landlord_statement: Bank statement file (PDF/Image)
    - tenant_data: JSON array of tenant transaction details
    
    EXPECTED tenant_data format:
    [
        {
            "utr_number": "123456789012",
            "amount": "5000", 
            "date": "2024-01-15",
            "confidence_score": 0.9,
            "extraction_notes": "Extracted from tenant 1 screenshot"
        },
        {
            "utr_number": "987654321098", 
            "amount": "7500",
            "date": "2024-01-16",
            "confidence_score": 0.85,
            "extraction_notes": "Extracted from tenant 2 screenshot"  
        }
        // ... more tenant records
    ]
    """
    
    print("DEBUG: Multi-tenant upload route called")
    
    try:
        # Check if bank statement file is present
        if 'landlord_statement' not in request.files:
            return jsonify({
                'success': False,
                'error': 'Bank statement file is required'
            }), 400
        
        landlord_file = request.files['landlord_statement']
        
        # Check if tenant data is provided in JSON format
        tenant_data_json = request.form.get('tenant_data')
        if not tenant_data_json:
            return jsonify({
                'success': False,
                'error': 'Tenant data array is required'
            }), 400
        
        # Parse tenant data array
        try:
            tenant_data_array = json.loads(tenant_data_json)
            if not isinstance(tenant_data_array, list):
                raise ValueError("Tenant data must be an array")
        except (json.JSONDecodeError, ValueError) as e:
            return jsonify({
                'success': False,
                'error': f'Invalid tenant data format: {str(e)}'
            }), 400
        
        print(f"DEBUG: Processing {len(tenant_data_array)} tenant records")
        
        # Validate bank statement file
        if not allowed_statement_file(landlord_file.filename):
            return jsonify({
                'success': False,
                'error': 'Bank statement must be PNG, JPG, JPEG, WEBP, HEIC, or PDF!'
            }), 400
        
        # Check if Gemini API is initialized
        if model is None:
            return jsonify({
                'success': False,
                'error': 'Gemini API not initialized. Check your Google Cloud configuration.'
            }), 500
        
        # Process files using temporary storage
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{landlord_file.filename.rsplit('.', 1)[1].lower()}") as landlord_temp:
            landlord_file.save(landlord_temp.name)
            landlord_temp_path = landlord_temp.name
        
        try:
            # Extract data from bank statement for all tenants
            print(f"DEBUG: Starting multi-tenant bank statement extraction")
            landlord_results = extract_upi_data_from_bank_statement_multi(landlord_temp_path, tenant_data_array)
            
            # Verify matches for all tenants
            print(f"DEBUG: Starting multi-tenant verification")
            verification_results = verify_utr_match_multi(tenant_data_array, landlord_results)
            
            # Prepare response
            response_data = {
                'success': True,
                'tenant_count': len(tenant_data_array),
                'results': verification_results,
                'summary': {
                    'total_tenants': len(verification_results),
                    'verified_matches': len([r for r in verification_results if r.get('match_status') == 'VERIFIED']),
                    'partial_matches': len([r for r in verification_results if r.get('match_status') == 'PARTIAL']),
                    'no_matches': len([r for r in verification_results if r.get('match_status') == 'NO_MATCH']),
                    'errors': len([r for r in verification_results if r.get('match_status') == 'ERROR'])
                }
            }
            
            print(f"DEBUG: Multi-tenant processing complete - {response_data['summary']}")
            
            return jsonify(response_data)
            
        finally:
            # Clean up temporary files
            try:
                os.unlink(landlord_temp_path)
            except OSError:
                pass
    
    except Exception as e:
        print(f"ERROR: Multi-tenant upload failed: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Processing failed: {str(e)}'
        }), 500

def example_your_workflow():
    """
    📖 EXAMPLE: Your exact workflow with pre-built tenant array
    
    This demonstrates how YOU will use the system:
    1. You extract data from multiple tenant UPI screenshots
    2. You create a tenant_data_array 
    3. You call the multi-tenant function with bank statement
    4. You get back verification results for all tenants
    """
    
    # 🏠 YOUR PRE-BUILT TENANT DATA ARRAY
    # (You create this from multiple tenant UPI screenshots)
    your_tenant_data = [
        {
            "utr_number": "240115123456",  # From tenant 1's UPI screenshot
            "amount": "15000",
            "date": "2024-01-15", 
            "confidence_score": 0.9,
            "extraction_notes": "Clear UTR from PhonePe screenshot - Tenant A"
        },
        {
            "utr_number": "240116789012",  # From tenant 2's UPI screenshot  
            "amount": "12000",
            "date": "2024-01-16",
            "confidence_score": 0.85,
            "extraction_notes": "UTR from Google Pay screenshot - Tenant B"
        },
        {
            "utr_number": "240117345678",  # From tenant 3's UPI screenshot
            "amount": "18000", 
            "date": "2024-01-17",
            "confidence_score": 0.8,
            "extraction_notes": "Paytm transaction UTR - Tenant C"
        },
        {
            "utr_number": "240118901234",  # From tenant 4's UPI screenshot
            "amount": "10000",
            "date": "2024-01-18", 
            "confidence_score": 0.75,
            "extraction_notes": "BHIM UPI receipt - Tenant D"
        }
    ]
    
    print(f"📊 PROCESSING {len(your_tenant_data)} TENANT TRANSACTIONS")
    print("=" * 60)
    
    # Show what you're processing
    for i, tenant in enumerate(your_tenant_data, 1):
        print(f"Tenant {i}: ₹{tenant['amount']} | UTR: {tenant['utr_number']} | Date: {tenant['date']}")
    
    print("=" * 60)
    
    # 🏦 PROCESS AGAINST BANK STATEMENT  
    # landlord_bank_statement_path = "/path/to/landlord_statement.pdf"
    # results = extract_upi_data_from_bank_statement_multi(landlord_bank_statement_path, your_tenant_data)
    # verification = verify_utr_match_multi(your_tenant_data, results)
    
    print("🎯 TO USE THIS SYSTEM:")
    print("1. Create your tenant_data array (like above)")
    print("2. Call: extract_upi_data_from_bank_statement_multi(bank_statement_path, your_tenant_data)")  
    print("3. Call: verify_utr_match_multi(your_tenant_data, results)")
    print("4. Or use API: POST to /upload-multi with landlord_statement file + tenant_data JSON")
    
    return your_tenant_data

def create_tenant_data_entry(utr_number, amount, date, confidence_score=0.8, notes=""):
    """
    🛠️ HELPER: Create a properly formatted tenant data entry
    
    Use this to build your tenant_data_array easily:
    
    Args:
        utr_number (str): UTR from tenant's UPI screenshot  
        amount (str): Transaction amount
        date (str): Transaction date (YYYY-MM-DD)
        confidence_score (float): How confident you are in the extraction (0.0-1.0)
        notes (str): Any additional notes about the extraction
    
    Returns:
        dict: Properly formatted tenant data entry
        
    Example:
        tenant1 = create_tenant_data_entry("123456789012", "5000", "2024-01-15", 0.9, "Clear PhonePe screenshot")
        tenant2 = create_tenant_data_entry("987654321098", "7500", "2024-01-16", 0.8, "Google Pay receipt")
        tenant_array = [tenant1, tenant2]
    """
    
    return {
        "utr_number": str(utr_number).strip(),
        "amount": str(amount).strip(), 
        "date": str(date).strip(),
        "confidence_score": max(0.0, min(1.0, float(confidence_score))),
        "extraction_notes": str(notes).strip() if notes else f"UTR: {utr_number}, Amount: ₹{amount}"
    }

def validate_tenant_data_array(tenant_data_array):
    """
    🔍 HELPER: Validate your tenant data array format
    
    Use this to check if your tenant_data_array is properly formatted before processing
    
    Args:
        tenant_data_array (list): Your array of tenant data
        
    Returns:
        tuple: (is_valid, error_message)
    """
    
    if not isinstance(tenant_data_array, list):
        return False, "tenant_data_array must be a list"
    
    if len(tenant_data_array) == 0:
        return False, "tenant_data_array cannot be empty"
    
    required_fields = ['utr_number', 'amount', 'date']
    
    for i, tenant in enumerate(tenant_data_array):
        if not isinstance(tenant, dict):
            return False, f"Tenant {i+1} must be a dictionary"
        
        for field in required_fields:
            if field not in tenant:
                return False, f"Tenant {i+1} missing required field: {field}"
            
            if not tenant[field] or str(tenant[field]).strip() == "":
                return False, f"Tenant {i+1} has empty {field}"
    
    return True, "Tenant data array is valid"

# Flask application entry point
if __name__ == '__main__':
    print("🚀 Starting UPI Verification Server...")
    print(f"📍 Project ID: {PROJECT_ID}")
    print(f"📍 Location: {LOCATION}")
    print(f"🔧 Max file size: {MAX_FILE_SIZE // (1024*1024)}MB")
    
    if model is not None:
        print("🎯 Gemini API: ✅ Connected")
    else:
        print("⚠️ Gemini API: ❌ Not Connected")
        print("Check your .env file and Google Cloud credentials")
    
    # Start the Flask development server
    app.run(
        host='0.0.0.0',    # Allow external connections
        port=5001,         # Run on port 5001
        debug=True,        # Enable debug mode for development
        threaded=True      # Handle multiple requests
    )
