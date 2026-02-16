# Grant Filtering System - Test Instructions

## Purpose

This test validates that the grant filtering system is working correctly by running the crawler against a test HTML page with 10 known grants (5 should pass, 5 should fail).

## Test Setup

The test environment consists of:

1. **Test HTML Page**: `test_grants_page.html` - Contains 10 grants with known expected outcomes
2. **LocalTest Profile**: `site_profiles/localtest.py` - Site profile configured to crawl the local test page

## Expected Results

### Grants That Should PASS (5 total)

1. **Digital Literacy Equipment Grant for African Schools** ✅
   - Perfect match: refurbished IT for African schools, nonprofit, children, digital gap
   - Deadline: June 30, 2025
   - Score: Should be ~90-100

2. **Computer Lab Setup for Rural Schools in Developing Countries** ✅
   - Strong match: computer labs for children in Africa, nonprofits eligible
   - Deadline: August 15, 2025
   - Score: Should be ~80-95

3. **E-Waste Recycling and Technology Access Program** ✅
   - Good match: e-waste refurbishment for schools in Africa
   - Deadline: September 30, 2025
   - Score: Should be ~70-85

4. **STEM Education Initiative for Underserved Youth** ✅
   - Relevant: STEM/tech education for African children, can fund equipment
   - Deadline: July 20, 2025
   - Score: Should be ~65-80

5. **Technology Infrastructure for African Educational Institutions** ✅
   - Relevant: technology equipment for schools in Africa
   - Deadline: October 1, 2025
   - Score: Should be ~60-75

### Grants That Should FAIL (5 total)

1. **Innovation Challenge: Best Tech Solution for African Education** ❌
   - Reason: Competition/award, not a grant
   - Expected: Should be filtered out by relevance score (<60)

2. **Technology Startup Accelerator for African Entrepreneurs** ❌
   - Reason: For-profit only, nonprofits not eligible
   - Expected: Should be filtered out by relevance score (<60)

3. **Digital Literacy Program for European Schools** ❌
   - Reason: Wrong geographic focus (Europe, not Africa)
   - Expected: Should be filtered out by relevance score (<60)

4. **Computer Donation Program for Kenyan Schools** ❌
   - Reason: Deadline has passed (December 1, 2024)
   - Expected: Should be filtered out by deadline check (before LLM analysis)

5. **E-Waste Management Infrastructure for African Cities** ❌
   - Reason: Not about children/schools/education - industrial recycling only
   - Expected: Should be filtered out by relevance score (<60)

## How to Run the Test

### Step 1: Update config.py

Temporarily enable only the `localtest` profile in your `config.py`:

```python
ENABLED_SITES = [
    "localtest",  # For testing only
    # "fundsforngos",  # Temporarily disabled
    # "eufundingportal",  # Temporarily disabled
]
```

### Step 2: Run the crawler

```bash
python main.py
```

### Step 3: Check the output

The crawler will create `grants_output.json`. Check the results:

**Expected outcome**: Exactly 5 grants should be saved to the output file.

### Step 4: Verify the results

Open `grants_output.json` and verify:

1. **Count**: Exactly 5 grants (not more, not less)
2. **Titles**: Should be the 5 grants from the "PASS" list above
3. **Relevance scores**: All should have `relevance_score >= 60`
4. **how_it_helps**: Each grant should have a specific, actionable explanation
5. **No expired grant**: The "Computer Donation Program for Kenyan Schools" (expired deadline) should NOT appear

### Step 5: Review the console output

Check the console for filtering messages:

- You should see grants being skipped due to deadline
- You should see grants being skipped due to low relevance scores
- You should see 5 grants being processed and saved

## Interpreting Results

### ✅ Test PASSED if:
- Exactly 5 grants in `grants_output.json`
- All 5 are from the expected "PASS" list
- No grants from the "FAIL" list appear
- All grants have relevance scores >= 60
- All grants have specific `how_it_helps` explanations

### ❌ Test FAILED if:
- More or fewer than 5 grants in output
- Any grants from the "FAIL" list appear
- Any expected "PASS" grants are missing
- Relevance scores are below 60
- `how_it_helps` fields are generic or empty

## Troubleshooting

### If you get 0 results:

1. Check that `MIN_RELEVANCE_SCORE` in `config.py` is set to 60 (not higher)
2. Check that `MIN_DEADLINE_DAYS` in `config.py` is set to 3 (not higher)
3. Verify the test HTML file path in `site_profiles/localtest.py` matches your system
4. Check console output for errors in LLM extraction

### If you get all 10 grants:

1. The relevance scoring is not working properly
2. Check that the LLM strategy is properly configured
3. Verify that `MIN_RELEVANCE_SCORE` filtering is being applied in `scraper_utils.py`

### If you get wrong grants:

1. Review the relevance scores in the output JSON
2. Check the `reasoning` and `how_it_helps` fields to understand why grants passed/failed
3. The LLM might be interpreting criteria differently than expected

## After Testing

### If test PASSED:
The filtering system is working correctly. The issue with real sources returning 0 results means:
- Those sources genuinely don't have any relevant grants currently, OR
- The CSS selectors for those sites need to be updated

### If test FAILED:
The filtering logic needs debugging:
1. Review the LLM extraction strategy in `scraper_utils.py`
2. Check the relevance scoring criteria
3. Verify date parsing and deadline validation
4. Test individual components separately

## Cleanup

After testing, restore your original `config.py`:

```python
ENABLED_SITES = [
    "fundsforngos",
    "eufundingportal",
    # "localtest",  # Comment out or remove
]
```

## Notes

- The test page is designed to be challenging with edge cases
- Some grants are borderline (scores around 60-65) to test threshold sensitivity
- The `how_it_helps` field quality is critical - it should explain specific use cases, not just list criteria
- Date parsing is tested with the expired grant (Dec 1, 2024)
