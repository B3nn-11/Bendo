# PyInstaller runtime hook for the Lite edition (see Bendo-Lite.spec).
# Runs inside the frozen exe before bendo.py, flipping it into Lite mode
# (core tools only). The regular build never runs this hook.
import os

os.environ["BENDO_LITE"] = "1"
