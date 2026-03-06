"""
Capital IQ Data Refresh Script

Automates the process of:
1. Opening the CIQ master Excel workbook
2. Triggering Capital IQ formulas to update
3. Waiting for the update to complete
4. Extracting the results to a CSV
5. Loading into the SQLite database

Requires:
- Windows with Excel installed
- Capital IQ Excel plugin installed and logged in
- xlwings package
"""

import sys
import time
import shutil
from pathlib import Path
from datetime import datetime

import pandas as pd
import xlwings as xw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import CIQ_TEMPLATES_DIR, CIQ_EXPORTS_DIR
from db.schema import get_connection
# loader functions would be imported here once built, e.g. upsert_financials

CIQ_MASTER_FILE = CIQ_TEMPLATES_DIR / "ciq_screener.xlsx"


def refresh_workbook():
    """Opens Excel, triggers CIQ refresh, and waits for completion."""
    if not CIQ_MASTER_FILE.exists():
        print(f"Error: {CIQ_MASTER_FILE} not found.")
        print("Please create this file with your CIQ templates first.")
        return None

    print(f"Opening {CIQ_MASTER_FILE.name}...")
    
    # Needs to be visible so the CIQ COM add-in can interact
    app = xw.App(visible=True)
    wb = app.books.open(CIQ_MASTER_FILE)
    
    print("Triggering calculation...")
    # This recalculates all Excel formulas. If CIQ requires a specific macro to refresh,
    # it would be called here e.g. app.macro("RefreshAll")()
    app.calculate()
    
    # Wait for CIQ formulas to resolve
    # CIQ often shows "Getting Data..." or "#REQ" while fetching
    print("Waiting for Capital IQ to fetch data...")
    
    # We poll a specific check cell to know when it's done.
    # Alternatively, just wait a fixed time.
    time.sleep(15) 
    
    # Try polling by checking a known cell on the 'Data' sheet.
    # We will look for '#REQ' or 'Getting Data'.
    try:
        ws = wb.sheets['Dashboard'] # adjust name as needed
        max_wait = 120
        elapsed = 0
        while elapsed < max_wait:
            val = str(ws.range('A1').value)
            if "getting data" in val.lower() or "#req" in val.lower():
                time.sleep(2)
                elapsed += 2
            else:
                break
    except Exception as e:
        print("Could not poll specific sheet; waiting fixed 30s instead.")
        time.sleep(30)
        
    print("Refresh assumed complete.")
    
    return app, wb


def extract_and_load(wb):
    """Extracts data from the active workbook and saves as CSV."""
    CIQ_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_csv = CIQ_EXPORTS_DIR / f"ciq_export_{today}.csv"
    latest_csv = CIQ_EXPORTS_DIR / "ciq_latest.csv"
    
    try:
        # Assuming the final output is neatly in a sheet called 'Export'
        ws = wb.sheets['Export'] 
        
        # Determine data range dynamically
        last_row = ws.range('A' + str(ws.cells.last_cell.row)).end('up').row
        last_col = ws.range('A1').end('right').column
        
        # Read the whole block into pandas
        print(f"Reading data from Export sheet (rows: {last_row}, cols: {last_col})...")
        data_range = ws.range((1, 1), (last_row, last_col)).value
        
        if not data_range:
            print("No data found on Export sheet.")
            return False
            
        # Create DataFrame (first row = header)
        df = pd.DataFrame(data_range[1:], columns=data_range[0])
        
        # Drop empty rows
        df.dropna(how='all', inplace=True)
        
        print(f"Extracted {len(df)} rows.")
        
        # Save CSV
        df.to_csv(out_csv, index=False)
        shutil.copy2(out_csv, latest_csv)
        print(f"Exported to {out_csv.name} and {latest_csv.name}")
        
        # Here we would load to SQLite: 
        # upsert_financials(df), etc.
        
        return True
        
    except Exception as e:
        print(f"Failed to extract data: {e}")
        return False
        

def main():
    print("=" * 50)
    print("CAPITAL IQ REFRESH AUTOMATION")
    print("=" * 50)
    
    CIQ_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    
    if not CIQ_MASTER_FILE.exists():
        print(f"\nMissing master template at: {CIQ_MASTER_FILE}")
        print("Please create an Excel file with your CIQ screening formulas.")
        print("Ensure it has an 'Export' sheet that references the data neatly.")
        return
        
    app, wb = refresh_workbook()
    if wb:
        success = extract_and_load(wb)
        
        print("\nClosing Excel...")
        wb.save()
        wb.close()
        app.quit()
        
        if success:
            print("\n✓ CIQ refresh pipeline complete")
        else:
            print("\n✗ Failed to extract data.")


if __name__ == "__main__":
    main()
