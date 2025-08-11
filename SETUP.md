# UPI Verification System - Setup Guide

## Prerequisites

1. **Google Cloud Account**: You need a Google Cloud account with billing enabled
2. **Python 3.8+**: Make sure Python is installed on your system

## Setup Instructions

### 1. Clone/Download the Project
```bash
cd /path/to/your/upi_verification
```

### 2. Install Dependencies
```bash
# Create and activate virtual environment (if not already done)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 3. Set up Google Cloud

#### Option A: Using gcloud CLI (Recommended)
```bash
# Install Google Cloud CLI
# Follow: https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth application-default login

# Set your project
gcloud config set project YOUR-PROJECT-ID
```

#### Option B: Using Service Account Key
```bash
# Download service account key from Google Cloud Console
# Place it in your project directory as 'service-account-key.json'
export GOOGLE_APPLICATION_CREDENTIALS="./service-account-key.json"
```

### 4. Enable Required APIs
```bash
# Enable Vertex AI API
gcloud services enable aiplatform.googleapis.com
```

### 5. Configure Environment Variables
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env file with your values:
# GCP_PROJECT_ID=your-google-cloud-project-id
# GCP_LOCATION=us-central1
# SECRET_KEY=your-secret-key-for-production
```

### 6. Test the Setup
```bash
python test_setup.py
```

### 7. Run the Application
```bash
python app.py
```

The application will be available at: http://localhost:5000

## Troubleshooting

### Common Issues:

1. **"GCP_PROJECT_ID not set"**
   - Make sure you have a `.env` file with your project ID

2. **"Authentication failed"**
   - Run `gcloud auth application-default login`
   - Or set GOOGLE_APPLICATION_CREDENTIALS environment variable

3. **"API not enabled"**
   - Enable Vertex AI API: `gcloud services enable aiplatform.googleapis.com`

4. **"Import errors"**
   - Make sure virtual environment is activated
   - Run `pip install -r requirements.txt`

### Environment Variables Reference:

- `GCP_PROJECT_ID`: Your Google Cloud Project ID (required)
- `GCP_LOCATION`: Google Cloud region (default: us-central1)
- `SECRET_KEY`: Flask secret key for sessions (required for production)
- `FLASK_ENV`: development or production (default: development)
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to service account key (optional if using gcloud auth)
