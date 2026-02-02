import os
import csv

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'mock_data_output')

EXPECTED_COUNTS = {
    'users.csv': 100_000,
    'projects.csv': 10_000,
    'tasks.csv': 200_000,
    'reports.csv': 10_000_000
}

def verify():
    print("Verifying generated data...")
    all_passed = True
    
    for filename, expected in EXPECTED_COUNTS.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(filepath):
            print(f"[FAIL] {filename} not found!")
            all_passed = False
            continue
            
        print(f"Checking {filename}...", end=' ')
        # Count lines efficiently
        try:
            with open(filepath, 'rb') as f:
                # -1 for header
                count = sum(1 for _ in f) - 1
            
            if count == expected:
                print(f"[PASS] Count: {count}")
            else:
                print(f"[FAIL] Expected {expected}, got {count}")
                all_passed = False
        except Exception as e:
            print(f"[ERROR] {e}")
            all_passed = False

    if all_passed:
        print("\nAll verifications passed successfully!")
    else:
        print("\nSome verifications failed.")

if __name__ == "__main__":
    verify()
