"""
Script to add accident_summary column to case_benefits table
"""

import sqlite3
import sys
from pathlib import Path

def add_accident_summary_column():
    """Add accident_summary column to case_benefits table if it doesn't exist"""
    
    # Connect to database
    db_path = Path(__file__).parent.parent / 'instance' / 'intellexia.db'
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(case_benefits)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'accident_summary' in columns:
            print("Column 'accident_summary' already exists in case_benefits table")
            return True
        
        # Add the column
        cursor.execute("""
            ALTER TABLE case_benefits 
            ADD COLUMN accident_summary TEXT
        """)
        
        conn.commit()
        print("Successfully added 'accident_summary' column to case_benefits table")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error adding column: {str(e)}")
        return False

if __name__ == '__main__':
    success = add_accident_summary_column()
    sys.exit(0 if success else 1)
