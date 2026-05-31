import sys
import os

# Ensure the backend directory is on sys.path so tests can import top-level
# modules (db, models, etc.) without package-prefix qualification.
sys.path.insert(0, os.path.dirname(__file__))
