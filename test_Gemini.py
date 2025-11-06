import google.generativeai as genai

# Configure with your valid API key
API_KEY = "AIzaSyAIoAqAk3KkhwtZo2CDpOEBm5QWd-xRZl0"  # Use the key that worked
genai.configure(api_key=API_KEY)

def generate_text(prompt):
    try:
        # Use one of the available models from your list
        # Let's use gemini-2.0-flash as it's widely available and free
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Generate content
        response = model.generate_content(prompt)
        
        return response.text
        
    except Exception as e:
        return f"Error: {str(e)}"

# Example usage
if __name__ == "__main__":
    prompt = "Explain quantum computing in simple terms in 3 sentences."
    
    result = generate_text(prompt)
    
    print("Generated Text:")
    print("=" * 50)
    print(result)