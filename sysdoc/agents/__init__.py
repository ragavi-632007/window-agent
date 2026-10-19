import sys
from pathlib import Path

# Add this directory to sys.path to support action_graph absolute imports
agents_dir = str(Path(__file__).parent.resolve())
if agents_dir not in sys.path:
    sys.path.insert(0, agents_dir)
