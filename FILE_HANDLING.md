# File Handling Documentation

## Overview
This UPI verification application uses **temporary file storage** for processing uploaded images. All buffer-based memory processing has been removed for better security and reliability.

## File Storage Location
- **Location**: System temporary directory (usually `/tmp` on macOS/Linux, `%TEMP%` on Windows)
- **Method**: Uses Python's `tempfile.NamedTemporaryFile()` with `delete=False`
- **File naming**: Auto-generated unique names with `.jpg` suffix
- **Access**: Only accessible by the application process

## File Lifecycle

### 1. Upload Process
```python
# Files are saved to temporary locations
with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
    uploaded_file.save(temp_file.name)
    temp_path = temp_file.name
```

### 2. Processing
- Images are processed directly from temporary file paths
- No data is stored in memory buffers
- OCR extraction uses file paths, not binary data

### 3. Cleanup
```python
# Files are explicitly deleted after processing
try:
    os.unlink(temp_path)
    print("Cleaned up temporary file")
except Exception as cleanup_error:
    print(f"Error cleaning temp files: {cleanup_error}")
```

## Security Features

### File Validation
- **Extensions**: Only PNG, JPG, JPEG, WEBP, HEIC allowed
- **Size limits**: Configured in `config.py` (default: 16MB)
- **Filename sanitization**: Uses `secure_filename()` for display only

### Temporary File Security
- Files are created with restrictive permissions
- Only the application process can access them
- Files are automatically deleted after processing
- No persistent storage of uploaded images

### Error Handling
- Cleanup happens in `finally` blocks to ensure deletion
- Graceful handling of cleanup errors
- No temporary files left behind on normal operation

## Implementation Details

### Web Upload Route (`/upload`)
1. Validates uploaded files
2. Creates temporary files for both tenant and landlord screenshots
3. Processes images using `extract_upi_data_from_file()`
4. Performs UTR verification
5. **Always** cleans up temporary files

### API Route (`/api/verify`)
1. Same validation and temporary file approach
2. Returns JSON response instead of HTML
3. Identical cleanup process
4. Consistent error handling

### Processing Function
```python
def extract_upi_data_from_file(image_path):
    """Extract UPI data from image file path (not buffer)"""
    with open(image_path, 'rb') as image_file:
        image_bytes = image_file.read()
    # Process with Vertex AI...
```

## Removed Components
- ❌ `process_image_buffer()` function
- ❌ `extract_upi_data_from_buffer()` function  
- ❌ Memory buffer processing
- ❌ In-memory image manipulation
- ❌ PIL Image buffer operations

## Benefits of This Approach

### Security
- No sensitive data in memory longer than necessary
- Temporary files have restricted access
- Automatic cleanup prevents data leakage

### Reliability
- Handles large files better than memory buffers
- Consistent processing between web and API endpoints
- Better error recovery

### Performance
- Reduces memory usage for large images
- Allows garbage collection of image data
- Scales better with concurrent requests

## Monitoring File Cleanup

The application logs cleanup operations:
```
DEBUG: Cleaned up temporary files
API: Error cleaning temp files: [error message]
```

Monitor these logs to ensure proper file cleanup in production.

## File System Requirements
- Write access to system temporary directory
- Sufficient disk space for concurrent uploads
- Regular cleanup of any orphaned temporary files (handled by OS)
