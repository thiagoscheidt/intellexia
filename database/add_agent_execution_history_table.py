"""
Migration: Add AgentExecutionHistory table to persist full agent execution context.

This table stores complete execution history for agents (system prompt, user message, 
response, full conversation context) for audit and debugging purposes.
"""

import sys
import os

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, db
from app.models import AgentExecutionHistory
import logging

logger = logging.getLogger(__name__)


def run_migration():
    """Create AgentExecutionHistory table."""
    with app.app_context():
        try:
            # Create the table
            db.create_all()
            logger.info("✓ AgentExecutionHistory table created successfully.")
            print("✓ AgentExecutionHistory table created successfully.")
        except Exception as e:
            logger.error(f"✗ Error creating AgentExecutionHistory table: {e}")
            print(f"✗ Error creating AgentExecutionHistory table: {e}")
            raise


if __name__ == "__main__":
    run_migration()
