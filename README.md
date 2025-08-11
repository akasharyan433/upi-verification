cat > README.md << 'EOF'
# UPI Transaction Verification System

An AI-powered system to verify UPI transactions by comparing tenant and landlord payment screenshots using Google's Gemini AI.

## 🚀 Features

- **AI-Powered OCR**: Extracts UPI transaction data using Google Vertex AI Gemini
- **UTR Verification**: Compares UTR numbers between tenant and landlord screenshots
- **Confidence Scoring**: Provides confidence levels for extracted data
- **Web Interface**: User-friendly upload and verification interface
- **REST API**: Programmatic access for integration
- **Secure Processing**: Temporary file handling with automatic cleanup

## 🛠️ Tech Stack

- **Backend**: Python Flask
- **AI/ML**: Google Vertex AI (Gemini Pro Vision)
- **Frontend**: HTML, CSS, JavaScript
- **Cloud**: Google Cloud Platform
- **Image Processing**: PIL/Pillow

## 📋 Prerequisites

- Python 3.8+
- Google Cloud Platform account
- Vertex AI API enabled
- Google Cloud CLI installed

## 🔧 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/upi-verification.git
   cd upi-verification