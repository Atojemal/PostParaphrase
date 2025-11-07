import google.generativeai as genai

# Configure with your API key
API_KEY = "AIzaSyD6VOpDF_pdpmIx_yGnce_dSvUVzxCiDUE"
genai.configure(api_key=API_KEY)

def list_available_models():
    try:
        models = genai.list_models()
        print("Available Models:")
        print("=" * 50)
        for model in models:
            print(f"Name: {model.name}")
            print(f"Supported Generation Methods: {model.supported_generation_methods}")
            print("-" * 30)
    except Exception as e:
        print(f"Error: {e}")

list_available_models()