import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Flask Configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # File Upload Limits (Still needed for validation)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Google Cloud AI Configuration (Still needed for Gemini)
    GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
    GCP_LOCATION = os.environ.get('GCP_LOCATION', 'us-central1')
    
    # Validate required environment variables
    if not GCP_PROJECT_ID:
        print("⚠️  Warning: GCP_PROJECT_ID not set in environment variables")
        print("Please create a .env file with your Google Cloud Project ID")
    
    # File Validation (Still needed)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'heic'}  # Images only for tenant
    ALLOWED_STATEMENT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'heic', 'pdf'}  # Images + PDF for bank statement
    
    # Buffer Processing Configuration (New settings)
    MAX_IMAGE_DIMENSION = 1024  # Max width/height for image optimization
    IMAGE_COMPRESSION_QUALITY = 85  # JPEG quality for processed images
    
    # Memory Management (Optional)
    MAX_CONCURRENT_UPLOADS = 5  # Limit simultaneous processing
    PROCESSING_TIMEOUT = 30  # Seconds before request timeout
    
    # Security Settings
    WTF_CSRF_ENABLED = True  # Enable CSRF protection
    WTF_CSRF_TIME_LIMIT = None  # No time limit for CSRF tokens

class DevelopmentConfig(Config):
    DEBUG = True
    FLASK_ENV = 'development'

class ProductionConfig(Config):
    DEBUG = False
    FLASK_ENV = 'production'
    
    # Enhanced security for production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Production memory limits
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # Smaller limit for production
    MAX_CONCURRENT_UPLOADS = 3

# Configuration selector
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
