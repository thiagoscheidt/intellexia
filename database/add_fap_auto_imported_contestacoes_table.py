"""Migration: Create fap_auto_imported_contestacoes table."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import FapAutoImportedContestacao, db


def upgrade():
    with app.app_context():
        FapAutoImportedContestacao.__table__.create(bind=db.engine, checkfirst=True)
        print("Table fap_auto_imported_contestacoes created successfully.")


if __name__ == '__main__':
    upgrade()
