#!/usr/bin/env python3
"""
Test script to verify JSON parsing logic for Gemini responses
"""

import json
import re

def test_json_parsing():
    """Test various Gemini response formats"""
    
    # Test cases with different response formats
    test_cases = [
        # Case 1: Clean JSON
        {
            "name": "Clean JSON",
            "response": '{"utr_number": "123456789012", "amount": "500", "date": "2024-01-15", "confidence_score": 0.9, "extraction_notes": "Clear UTR visible"}',
            "should_parse": True
        },
        # Case 2: JSON in markdown code block
        {
            "name": "Markdown JSON block",
            "response": '```json\n{"utr_number": "123456789012", "amount": "500", "date": "2024-01-15", "confidence_score": 0.9, "extraction_notes": "Clear UTR visible"}\n```',
            "should_parse": True
        },
        # Case 3: JSON in plain code block
        {
            "name": "Plain code block",
            "response": '```\n{"utr_number": "123456789012", "amount": "500", "date": "2024-01-15", "confidence_score": 0.9, "extraction_notes": "Clear UTR visible"}\n```',
            "should_parse": True
        },
        # Case 4: JSON with extra text
        {
            "name": "JSON with extra text",
            "response": 'Here is the extracted data:\n{"utr_number": "123456789012", "amount": "500", "date": "2024-01-15", "confidence_score": 0.9, "extraction_notes": "Clear UTR visible"}\nThis data was extracted from the image.',
            "should_parse": True
        },
        # Case 5: Invalid JSON
        {
            "name": "Invalid JSON",
            "response": 'This is not valid JSON at all. No brackets or structure.',
            "should_parse": False
        }
    ]
    
    print("🧪 Testing JSON Parsing Logic\n")
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        
        # Apply the same parsing logic as in the app
        extracted_data = None
        response_text = test_case['response'].strip()
        
        # Strategy 1: Direct JSON parsing
        try:
            extracted_data = json.loads(response_text)
            print("  ✅ Strategy 1 (Direct JSON) - SUCCESS")
        except json.JSONDecodeError:
            print("  ❌ Strategy 1 (Direct JSON) - FAILED")
        
        # Strategy 2: Extract JSON from markdown code blocks
        if extracted_data is None:
            json_pattern = r'```(?:json)?\s*(.*?)\s*```'
            match = re.search(json_pattern, response_text, re.DOTALL)
            if match:
                try:
                    json_text = match.group(1).strip()
                    extracted_data = json.loads(json_text)
                    print("  ✅ Strategy 2 (Markdown) - SUCCESS")
                except json.JSONDecodeError:
                    print("  ❌ Strategy 2 (Markdown) - FAILED")
            else:
                print("  ❌ Strategy 2 (Markdown) - NO MATCH")
        
        # Strategy 3: Look for JSON-like content between { and }
        if extracted_data is None:
            try:
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_text = response_text[start_idx:end_idx+1]
                    extracted_data = json.loads(json_text)
                    print("  ✅ Strategy 3 (Bracket extraction) - SUCCESS")
                else:
                    print("  ❌ Strategy 3 (Bracket extraction) - NO BRACKETS")
            except json.JSONDecodeError:
                print("  ❌ Strategy 3 (Bracket extraction) - FAILED")
        
        # Check result
        if extracted_data is not None:
            print(f"  📋 Extracted data: {extracted_data}")
            if test_case['should_parse']:
                print("  🎉 PASS - Successfully parsed as expected")
            else:
                print("  ⚠️  UNEXPECTED - Parsed when it shouldn't have")
        else:
            if test_case['should_parse']:
                print("  ❌ FAIL - Should have parsed but didn't")
            else:
                print("  🎉 PASS - Correctly failed to parse invalid JSON")
        
        print()

if __name__ == "__main__":
    test_json_parsing()
