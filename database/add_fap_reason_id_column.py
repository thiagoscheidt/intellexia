"""
Script to add fap_reason_id column to case_benefits table
This column creates a foreign key relationship with fap_reasons table
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent))

def add_fap_reason_id_column():
    """Add fap_reason_id column to case_benefits table if it doesn't exist"""
    
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
        
        if 'fap_reason_id' in columns:
            print("Column 'fap_reason_id' already exists in case_benefits table")
            return True
        
        # Add the column
        cursor.execute("""
            ALTER TABLE case_benefits 
            ADD COLUMN fap_reason_id INTEGER
        """)
        
        # Add the foreign key constraint as comment (SQLite doesn't enforce FKs in ALTER TABLE)
        # The constraint is defined in the model and will be enforced when recreating the table
        
        conn.commit()
        print("Successfully added 'fap_reason_id' column to case_benefits table")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error adding column: {str(e)}")
        return False

if __name__ == '__main__':
    success = add_fap_reason_id_column()
    sys.exit(0 if success else 1)
