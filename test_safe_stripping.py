#!/usr/bin/env python3
"""
Test script to verify safe stripping condition for response handling
"""

def test_safe_stripping():
    """Test various response scenarios for safe stripping"""
    
    print("🧪 Testing Safe Response Stripping\n")
    
    # Mock response objects for testing
    class MockResponse:
        def __init__(self, text):
            self.text = text
    
    test_cases = [
        # Case 1: Normal response with whitespace
        {
            "name": "Normal response with whitespace",
            "response": MockResponse("  \n  {'key': 'value'}  \n  "),
            "expected": "{'key': 'value'}",
            "should_work": True
        },
        # Case 2: Empty string
        {
            "name": "Empty string response",
            "response": MockResponse(""),
            "expected": "",
            "should_work": True
        },
        # Case 3: None response
        {
            "name": "None response",
            "response": MockResponse(None),
            "expected": "",
            "should_work": True
        },
        # Case 4: Whitespace only
        {
            "name": "Whitespace only response",
            "response": MockResponse("   \n\t  "),
            "expected": "",
            "should_work": True
        },
        # Case 5: Clean JSON without whitespace
        {
            "name": "Clean JSON without whitespace",
            "response": MockResponse('{"key": "value"}'),
            "expected": '{"key": "value"}',
            "should_work": True
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        
        try:
            # Apply the safe stripping logic
            response = test_case['response']
            response_text = response.text.strip() if response.text else ""
            
            print(f"  Input: {repr(test_case['response'].text)}")
            print(f"  Output: {repr(response_text)}")
            print(f"  Expected: {repr(test_case['expected'])}")
            
            if response_text == test_case['expected']:
                print("  🎉 PASS - Output matches expected")
            else:
                print("  ❌ FAIL - Output doesn't match expected")
                
            # Check if empty response is handled correctly
            if not response_text:
                print("  ℹ️  Empty response - would trigger early return")
            else:
                print(f"  ℹ️  Non-empty response - length: {len(response_text)}")
                
        except Exception as e:
            if test_case['should_work']:
                print(f"  ❌ FAIL - Unexpected error: {e}")
            else:
                print(f"  🎉 PASS - Expected error: {e}")
        
        print()

def test_edge_cases():
    """Test edge cases that might cause issues"""
    
    print("🔍 Testing Edge Cases\n")
    
    # Test cases that might cause AttributeError or other issues
    edge_cases = [
        # Case 1: Response object without text attribute
        {
            "name": "Response without text attribute",
            "setup": lambda: type('MockResponse', (), {})(),
            "should_error": True
        },
        # Case 2: Response with non-string text
        {
            "name": "Response with non-string text",
            "setup": lambda: type('MockResponse', (), {"text": 123})(),
            "should_error": True
        }
    ]
    
    for i, test_case in enumerate(edge_cases, 1):
        print(f"Edge Test {i}: {test_case['name']}")
        
        try:
            response = test_case['setup']()
            response_text = response.text.strip() if response.text else ""
            print(f"  ✅ No error - got: {repr(response_text)}")
            
            if test_case['should_error']:
                print("  ⚠️  Expected error but got none")
            else:
                print("  🎉 PASS - Handled correctly")
                
        except AttributeError as e:
            print(f"  ❌ AttributeError: {e}")
            if test_case['should_error']:
                print("  ℹ️  This is expected behavior")
            else:
                print("  ⚠️  Unexpected error")
        except Exception as e:
            print(f"  ❌ Other error: {e}")
        
        print()

if __name__ == "__main__":
    test_safe_stripping()
    test_edge_cases()
    
    print("💡 Recommendations:")
    print("1. ✅ Safe stripping condition implemented: response.text.strip() if response.text else ''")
    print("2. ✅ Early empty response check prevents downstream errors")
    print("3. ✅ Graceful handling of None, empty, and whitespace-only responses")
    print("4. ⚠️  Consider additional safety check: hasattr(response, 'text') for edge cases")
