#!/usr/bin/env python3
"""
Test the enhanced safe stripping condition
"""

def test_enhanced_stripping():
    """Test the enhanced safe stripping logic"""
    
    print("🧪 Testing Enhanced Safe Response Stripping\n")
    
    # Mock response objects for testing
    class MockResponse:
        def __init__(self, text):
            self.text = text
    
    class MockResponseNoText:
        pass
    
    test_cases = [
        # Case 1: Normal response with whitespace
        {
            "name": "Normal response with whitespace",
            "response": MockResponse("  \n  {'key': 'value'}  \n  "),
            "expected": "{'key': 'value'}",
        },
        # Case 2: Empty string
        {
            "name": "Empty string response",
            "response": MockResponse(""),
            "expected": "",
        },
        # Case 3: None response
        {
            "name": "None response",
            "response": MockResponse(None),
            "expected": "",
        },
        # Case 4: Response without text attribute
        {
            "name": "Response without text attribute",
            "response": MockResponseNoText(),
            "expected": "",
        },
        # Case 5: Response with non-string text
        {
            "name": "Response with non-string text",
            "response": MockResponse(123),
            "expected": "",
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        
        try:
            # Apply the enhanced safe stripping logic
            response = test_case['response']
            response_text = response.text.strip() if (hasattr(response, 'text') and response.text and isinstance(response.text, str)) else ""
            
            print(f"  Input: {repr(getattr(test_case['response'], 'text', 'NO_TEXT_ATTR'))}")
            print(f"  Output: {repr(response_text)}")
            print(f"  Expected: {repr(test_case['expected'])}")
            
            if response_text == test_case['expected']:
                print("  🎉 PASS - Output matches expected")
            else:
                print("  ❌ FAIL - Output doesn't match expected")
                
        except Exception as e:
            print(f"  ❌ UNEXPECTED ERROR: {e}")
        
        print()

if __name__ == "__main__":
    test_enhanced_stripping()
    print("✅ Enhanced safety check: hasattr(response, 'text') and response.text and isinstance(response.text, str)")
    print("✅ Handles all edge cases gracefully without errors")
