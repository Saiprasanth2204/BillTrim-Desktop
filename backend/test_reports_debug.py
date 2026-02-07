#!/usr/bin/env python3
"""
Test script to call the reports endpoints for debugging.
Run this while your debugger is attached to see the flow.
"""
import requests
import json

BASE_URL = "http://127.0.0.1:8765/api/v1"

# You'll need to add your auth token here
# Get it from browser dev tools -> Network -> Request Headers -> Authorization
AUTH_TOKEN = "YOUR_TOKEN_HERE"  # Replace with actual token

headers = {
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json"
}

def test_revenue_daily():
    """Test the revenue/daily endpoint"""
    print("=" * 80)
    print("Testing /reports/revenue/daily")
    print("=" * 80)
    
    params = {
        "start_date": "2026-01-31T18:30:00.000Z",
        "end_date": "2026-02-28T18:29:59.999Z",
        "branch_id": 1
    }
    
    print(f"Request URL: {BASE_URL}/reports/revenue/daily")
    print(f"Params: {json.dumps(params, indent=2)}")
    print("\nMaking request...")
    print("(Set breakpoints in reports.py before running this)\n")
    
    try:
        response = requests.get(
            f"{BASE_URL}/reports/revenue/daily",
            params=params,
            headers=headers
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")


def test_attendance_daily():
    """Test the attendance/daily endpoint"""
    print("=" * 80)
    print("Testing /reports/attendance/daily")
    print("=" * 80)
    
    params = {
        "start_date": "2026-01-31T18:30:00.000Z",
        "end_date": "2026-02-28T18:29:59.999Z",
        "branch_id": 1
    }
    
    print(f"Request URL: {BASE_URL}/reports/attendance/daily")
    print(f"Params: {json.dumps(params, indent=2)}")
    print("\nMaking request...")
    print("(Set breakpoints in reports.py before running this)\n")
    
    try:
        response = requests.get(
            f"{BASE_URL}/reports/attendance/daily",
            params=params,
            headers=headers
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("Reports Endpoint Debug Test Script")
    print("=" * 80)
    print("\nInstructions:")
    print("1. Start your backend server in DEBUG mode")
    print("2. Set breakpoints in backend/app/api/v1/endpoints/reports.py")
    print("3. Update AUTH_TOKEN in this script with your actual token")
    print("4. Run this script - debugger will stop at your breakpoints")
    print("\n" + "=" * 80 + "\n")
    
    # Uncomment the test you want to run:
    # test_revenue_daily()
    # test_attendance_daily()
