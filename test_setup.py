# test_setup.py
import os
from dotenv import load_dotenv

load_dotenv()

def test_environment():
    """Test basic environment setup"""
    PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
    LOCATION = os.environ.get('GCP_LOCATION', 'us-central1')
    
    print("🔧 Environment Test:")
    print(f"   Project ID: {PROJECT_ID}")
    print(f"   Location: {LOCATION}")
    
    if not PROJECT_ID:
        print("❌ GCP_PROJECT_ID not found in environment variables")
        return False
    
    print("✅ Environment variables are set correctly")
    return True

def test_vertexai_connection():
    """Test Vertex AI connection"""
    try:
        import vertexai
        from vertexai.preview.generative_models import GenerativeModel
        
        PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
        LOCATION = os.environ.get('GCP_LOCATION', 'us-central1')
        
        print("\n🤖 Vertex AI Test:")
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        
        # Try different model names
        model_names = ["gemini-1.0-pro", "gemini-pro", "text-bison"]
        
        for model_name in model_names:
            try:
                print(f"   Trying model: {model_name}")
                model = GenerativeModel(model_name)
                response = model.generate_content("Hello, test connection")
                print(f"✅ SUCCESS! Connected with model: {model_name}")
                print(f"   Response: {response.text[:100]}...")
                return True
            except Exception as e:
                print(f"   ❌ Failed with {model_name}: {str(e)[:100]}...")
                continue
        
        print("❌ No working models found")
        return False
        
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        return False

if __name__ == "__main__":
    print("🚀 UPI Verification System - Setup Test\n")
    
    env_ok = test_environment()
    if env_ok:
        ai_ok = test_vertexai_connection()
        
        if ai_ok:
            print("\n🎉 All tests passed! Your setup is ready.")
        else:
            print("\n⚠️  Environment OK, but AI connection failed.")
            print("   Please check your Google Cloud setup and enabled APIs.")
    else:
        print("\n❌ Environment setup incomplete. Please check your .env file.")
