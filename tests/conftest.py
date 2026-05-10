import sys
from pathlib import Path

# Make project root importable so tests can `import scrapers.calendar_picker_scraper`
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES_DIR = Path(__file__).parent / "fixtures"
