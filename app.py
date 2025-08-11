from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import json
import uuid
from werkzeug.utils import secure_filename
import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part
import base64
import io
from PIL import Image
import tempfile
import os
from config import config

app = Flask(__name__)

# Load configuration based on environment
config_name = os.environ.get('FLASK_ENV', 'default')
app.config.from_object(config[config_name])

# Configuration from config.py
ALLOWED_EXTENSIONS = app.config['ALLOWED_EXTENSIONS']
MAX_FILE_SIZE = app.config['MAX_CONTENT_LENGTH']
PROJECT_ID = app.config['GCP_PROJECT_ID']
LOCATION = app.config['GCP_LOCATION']

# Initialize Vertex AI with error handling
model = None
try:
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID not found in environment variables")
    
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.5-pro")
    print(f"✅ Successfully connected to Vertex AI - Project: {PROJECT_ID}, Location: {LOCATION}")
except Exception as e:
    print(f"❌ Failed to initialize Vertex AI: {str(e)}")
    print("Please check your Google Cloud credentials and project settings in .env file")
    print("Make sure you have:")
    print("1. Set GCP_PROJECT_ID in .env")
    print("2. Configured GOOGLE_APPLICATION_CREDENTIALS or used 'gcloud auth application-default login'")
    print("3. Enabled Vertex AI API in your Google Cloud project")

def allowed_file(filename):
    """Check if uploaded file has allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_image_buffer(file_buffer):
    """Process image from memory buffer and return optimized bytes"""
    try:
        # Open image from buffer
        image = Image.open(io.BytesIO(file_buffer))
        
        # Convert RGBA to RGB if necessary
        if image.mode == 'RGBA':
            # Create white background for transparency
            white_bg = Image.new('RGB', image.size, (255, 255, 255))
            white_bg.paste(image, mask=image.split()[-1] if len(image.split()) == 4 else None)
            image = white_bg
        elif image.mode not in ['RGB', 'L']:
            image = image.convert('RGB')
        
        # Use config values for optimization
        max_dimension = app.config['MAX_IMAGE_DIMENSION']
        max_size = (max_dimension, max_dimension)
        
        # Resize if too large
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Save to buffer as JPEG with compression
        output_buffer = io.BytesIO()
        image.save(output_buffer, 
                  format='JPEG', 
                  quality=app.config['IMAGE_COMPRESSION_QUALITY'], 
                  optimize=True)
        output_buffer.seek(0)
        
        return output_buffer.getvalue()
        
    except Exception as e:
        raise Exception(f"Image processing failed: {str(e)}")

def extract_upi_data_from_file(image_path):
    """Extract UPI transaction data using Gemini from image file"""
    
    # Check if model is initialized
    if model is None:
        return {
            "error": "Gemini API not initialized. Check your Google Cloud configuration.",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
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
        
        # Enhanced prompt for UPI data extraction
        prompt = """
        Analyze this UPI transaction screenshot and extract the following information:
        
        REQUIRED FIELDS:
        - utr_number: 12-digit UTR/Reference number (look for labels like "UTR:", "Ref No:", "Transaction ID:")
        - amount: Transaction amount (numerical value only)
        - currency: Currency code (usually INR)
        - date: Transaction date (YYYY-MM-DD format)
        - time: Transaction time (HH:MM format)
        - app_name: UPI app name (PhonePe, Google Pay, Paytm, BHIM, etc.)
        - transaction_status: Success/Failed/Pending
        - sender_upi: Sender's UPI ID
        - receiver_upi: Receiver's UPI ID
        
        IMPORTANT INSTRUCTIONS:
        1. Focus specifically on finding the UTR number - it's typically 12 digits
        2. If UTR is not clearly visible, set confidence_score to low (< 0.5)
        3. Extract exact text as shown in the image
        4. Return ONLY valid, clearly visible data
        5. If a field is not visible, return empty string ""
        
        Return the data in this JSON format:
        {
            "utr_number": "string",
            "amount": "string",
            "currency": "string",
            "date": "string",
            "time": "string",
            "app_name": "string",
            "transaction_status": "string",
            "sender_upi": "string",
            "receiver_upi": "string",
            "confidence_score": 0.0-1.0,
            "extraction_notes": "any important observations"
        }
        """
        
        # Generate response
        response = model.generate_content(
            [image_part, prompt],
            generation_config={
                "max_output_tokens": 2048,
                "temperature": 0.1
            }
        )
        
        # Try to parse JSON response, handle if it's not valid JSON
        try:
            extracted_data = json.loads(response.text)
        except json.JSONDecodeError:
            # If response is not JSON, try to extract from text
            response_text = response.text.strip()
            if response_text.startswith('```json') and response_text.endswith('```'):
                json_text = response_text[7:-3].strip()
                extracted_data = json.loads(json_text)
            else:
                raise json.JSONDecodeError("Invalid JSON response", response.text, 0)
        
        # Ensure all required fields exist with default values
        default_data = {
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "confidence_score": 0.0,
            "extraction_notes": ""
        }
        
        # Merge extracted data with defaults
        for key in default_data:
            if key not in extracted_data:
                extracted_data[key] = default_data[key]
        
        return extracted_data
        
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse API response as JSON: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": "JSON parsing failed"
        }
    except Exception as e:
        return {
            "error": f"OCR extraction failed: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": f"Extraction error: {str(e)}"
        }
    """Extract UPI transaction data using Gemini 2.5 Flash from image bytes"""
    
    # Check if model is initialized
    if model is None:
        return {
            "error": "Gemini API not initialized. Check your Google Cloud configuration.",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": "API initialization failed"
        }
    
    try:
        # Create image part directly from bytes
        image_part = Part.from_data(
            data=image_bytes,
            mime_type="image/jpeg"
        )
        
        # Enhanced prompt for UPI data extraction
        prompt = """
        Analyze this UPI transaction screenshot and extract the following information:
        
        REQUIRED FIELDS:
        - utr_number: 12-digit UTR/Reference number (look for labels like "UTR:", "Ref No:", "Transaction ID:")
        - amount: Transaction amount (numerical value only)
        - currency: Currency code (usually INR)
        - date: Transaction date (YYYY-MM-DD format)
        - time: Transaction time (HH:MM format)
        - app_name: UPI app name (PhonePe, Google Pay, Paytm, BHIM, etc.)
        - transaction_status: Success/Failed/Pending
        - sender_upi: Sender's UPI ID
        - receiver_upi: Receiver's UPI ID
        
        IMPORTANT INSTRUCTIONS:
        1. Focus specifically on finding the UTR number - it's typically 12 digits
        2. If UTR is not clearly visible, set confidence_score to low (< 0.5)
        3. Extract exact text as shown in the image
        4. Return ONLY valid, clearly visible data
        5. If a field is not visible, return empty string ""
        
        Return the data in this JSON format:
        {
            "utr_number": "string",
            "amount": "string",
            "currency": "string",
            "date": "string",
            "time": "string",
            "app_name": "string",
            "transaction_status": "string",
            "sender_upi": "string",
            "receiver_upi": "string",
            "confidence_score": 0.0-1.0,
            "extraction_notes": "any important observations"
        }
        """
        
        # Generate response
        response = model.generate_content(
            [image_part, prompt],
            generation_config={
                "max_output_tokens": 2048,
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        )
        
        extracted_data = json.loads(response.text)
        
        # Ensure all required fields exist with default values
        default_data = {
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "confidence_score": 0.0,
            "extraction_notes": ""
        }
        
        # Merge extracted data with defaults
        for key in default_data:
            if key not in extracted_data:
                extracted_data[key] = default_data[key]
        
        return extracted_data
        
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse API response as JSON: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": "JSON parsing failed"
        }
    except Exception as e:
        return {
            "error": f"OCR extraction failed: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": f"Extraction error: {str(e)}"
        }

def extract_upi_data_from_buffer(image_bytes):
    """Extract UPI transaction data using Gemini from image bytes (for API compatibility)"""
    
    # Check if model is initialized
    if model is None:
        return {
            "error": "Gemini API not initialized. Check your Google Cloud configuration.",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": "API initialization failed"
        }
    
    try:
        # Create image part directly from bytes
        image_part = Part.from_data(
            data=image_bytes,
            mime_type="image/jpeg"
        )
        
        # Enhanced prompt for UPI data extraction
        prompt = """
        Analyze this UPI transaction screenshot and extract the following information:
        
        REQUIRED FIELDS:
        - utr_number: 12-digit UTR/Reference number (look for labels like "UTR:", "Ref No:", "Transaction ID:")
        - amount: Transaction amount (numerical value only)
        - currency: Currency code (usually INR)
        - date: Transaction date (YYYY-MM-DD format)
        - time: Transaction time (HH:MM format)
        - app_name: UPI app name (PhonePe, Google Pay, Paytm, BHIM, etc.)
        - transaction_status: Success/Failed/Pending
        - sender_upi: Sender's UPI ID
        - receiver_upi: Receiver's UPI ID
        
        IMPORTANT INSTRUCTIONS:
        1. Focus specifically on finding the UTR number - it's typically 12 digits
        2. If UTR is not clearly visible, set confidence_score to low (< 0.5)
        3. Extract exact text as shown in the image
        4. Return ONLY valid, clearly visible data
        5. If a field is not visible, return empty string ""
        
        Return the data in this JSON format:
        {
            "utr_number": "string",
            "amount": "string",
            "currency": "string",
            "date": "string",
            "time": "string",
            "app_name": "string",
            "transaction_status": "string",
            "sender_upi": "string",
            "receiver_upi": "string",
            "confidence_score": 0.0-1.0,
            "extraction_notes": "any important observations"
        }
        """
        
        # Generate response
        response = model.generate_content(
            [image_part, prompt],
            generation_config={
                "max_output_tokens": 2048,
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        )
        
        extracted_data = json.loads(response.text)
        
        # Ensure all required fields exist with default values
        default_data = {
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "confidence_score": 0.0,
            "extraction_notes": ""
        }
        
        # Merge extracted data with defaults
        for key in default_data:
            if key not in extracted_data:
                extracted_data[key] = default_data[key]
        
        return extracted_data
        
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse API response as JSON: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": "JSON parsing failed"
        }
    except Exception as e:
        return {
            "error": f"OCR extraction failed: {str(e)}",
            "confidence_score": 0.0,
            "utr_number": "",
            "amount": "",
            "currency": "",
            "date": "",
            "time": "",
            "app_name": "",
            "transaction_status": "",
            "sender_upi": "",
            "receiver_upi": "",
            "extraction_notes": f"Extraction error: {str(e)}"
        }

def verify_utr_match(tenant_data, landlord_data):
    """Compare UTR numbers and validate transaction match"""
    
    print(tenant_data)
    print(landlord_data)

    tenant_utr = tenant_data.get('utr_number', '').strip()
    landlord_utr = landlord_data.get('utr_number', '').strip()
    
    # Basic UTR validation
    def is_valid_utr(utr):
        return utr.isdigit()
    
    tenant_valid = is_valid_utr(tenant_utr)
    landlord_valid = is_valid_utr(landlord_utr)
    
    match_found = tenant_utr == landlord_utr and tenant_valid and landlord_valid
    
    # Additional validation checks
    validation_checks = {
        'utr_match': match_found,
        'tenant_utr_valid': tenant_valid,
        'landlord_utr_valid': landlord_valid,
        'amount_match': tenant_data.get('amount') == landlord_data.get('amount'),
        'both_success': (
            tenant_data.get('transaction_status', '').lower() == 'success' and
            landlord_data.get('transaction_status', '').lower() == 'success'
        )
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
    """Handle file upload and processing using buffer storage"""
    
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
    
    if not (allowed_file(tenant_file.filename) and allowed_file(landlord_file.filename)):
        print(f"DEBUG: Invalid file types. Tenant: {allowed_file(tenant_file.filename)}, Landlord: {allowed_file(landlord_file.filename)}")
        flash('Invalid file format! Please upload PNG, JPG, JPEG, WEBP, or HEIC files.')
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
            
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_landlord:
            landlord_file.save(temp_landlord.name)
            landlord_temp_path = temp_landlord.name
            
        print(f"DEBUG: Saved temp files: {tenant_temp_path}, {landlord_temp_path}")
        
        try:
            # Process images using file paths instead of buffers
            print("DEBUG: Processing images from temp files...")
            tenant_data = extract_upi_data_from_file(tenant_temp_path)
            print("DEBUG: Tenant data extracted")
            landlord_data = extract_upi_data_from_file(landlord_temp_path)
            print("DEBUG: Landlord data extracted")
            
            print(f"DEBUG: Tenant data: {tenant_data}")
            print(f"DEBUG: Landlord data: {landlord_data}")
            
            # Check for extraction errors
            print("DEBUG: Checking for extraction errors...")
            if 'error' in tenant_data or 'error' in landlord_data:
                error_msg = "OCR extraction failed: "
                if 'error' in tenant_data:
                    error_msg += f"Tenant: {tenant_data['error']} "
                if 'error' in landlord_data:
                    error_msg += f"Landlord: {landlord_data['error']}"
                print(f"DEBUG: Extraction error: {error_msg}")
                flash(error_msg)
                return redirect(url_for('index'))
            
            print("DEBUG: No extraction errors, verifying UTR match...")
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
    """API endpoint for programmatic access using buffer storage"""
    
    if 'tenant_screenshot' not in request.files or 'landlord_screenshot' not in request.files:
        return jsonify({'error': 'Both files required'}), 400
    
    # Check if Gemini API is initialized
    if model is None:
        return jsonify({'error': 'Gemini API not initialized. Check Google Cloud configuration.'}), 500
    
    try:
        tenant_file = request.files['tenant_screenshot']
        landlord_file = request.files['landlord_screenshot']
        
        # Validate file types
        if not (allowed_file(tenant_file.filename) and allowed_file(landlord_file.filename)):
            return jsonify({'error': 'Invalid file format. Supported: PNG, JPG, JPEG, WEBP, HEIC'}), 400
        
        # Read files into memory buffers
        tenant_buffer = tenant_file.read()
        landlord_buffer = landlord_file.read()
        
        # Validate file sizes
        if len(tenant_buffer) > MAX_FILE_SIZE or len(landlord_buffer) > MAX_FILE_SIZE:
            return jsonify({'error': f'File size too large. Maximum {MAX_FILE_SIZE // (1024*1024)}MB allowed'}), 400
        
        # Process images from buffers
        tenant_processed = process_image_buffer(tenant_buffer)
        landlord_processed = process_image_buffer(landlord_buffer)
        
        # Extract data and verify
        tenant_data = extract_upi_data_from_buffer(tenant_processed)
        landlord_data = extract_upi_data_from_buffer(landlord_processed)
        
        # Check for extraction errors
        if 'error' in tenant_data or 'error' in landlord_data:
            return jsonify({
                'error': 'OCR extraction failed',
                'tenant_error': tenant_data.get('error'),
                'landlord_error': landlord_data.get('error')
            }), 422
        
        verification_result = verify_utr_match(tenant_data, landlord_data)
        
        return jsonify(verification_result)
    
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    status = {
        'status': 'healthy',
        'gemini_api': 'connected' if model is not None else 'disconnected',
        'project_id': PROJECT_ID or 'not_set',
        'location': LOCATION
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
    print(f"🎯 Gemini API: {'✅ Connected' if model else '❌ Not connected'}")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
