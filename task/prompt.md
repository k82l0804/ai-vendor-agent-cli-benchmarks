This directory is a small Python project (cart.py, test_cart.py). Use your tools; do not guess.
1. Run 'python3 -m pytest -q' and note the failures.
2. Find the root cause of the failing tests and fix it in cart.py.
3. Add a function apply_coupon(total, code) to cart.py: code 'SAVE10' takes 10% off, 'HALF' takes 50% off, 'FREE' makes the total 0.0; codes are case-insensitive; an unknown code raises ValueError; a negative total raises ValueError.
4. Add tests for apply_coupon to test_cart.py.
5. Run all tests and keep going until they pass.
6. Write NOTES.txt (plain text) summarizing what you changed.
Finish with a 2-line summary.
