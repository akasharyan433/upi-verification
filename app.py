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

if __name__ == '__main__':
    # Validate required environment variables on startup
    if not PROJECT_ID:
        print("❌ Error: GCP_PROJECT_ID not set in environment variables")
        print("Please set GCP_PROJECT_ID in your .env file")
        exit(1)
    
    # Show startup info
    print(f"🚀 Starting UPI Verification Server...")
    print(f"📍 Project ID: {PROJECT_ID}")
    print(f"📍 Location: {LOCATION}")
    print(f"🔧 Max file size: {MAX_FILE_SIZE // (1024*1024)}MB")
    print(f"📄 PDF support: ✅ Native processing (no conversion needed)")
    print(f"🎯 Gemini API: {'✅ Connected' if model else '❌ Not connected'}")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
