#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# vCard Studio — Mac launcher
# Double-click this file to start vCard Studio in your browser.
#
# If macOS asks "Are you sure you want to open this?" click Open.
# To allow it permanently: right-click → Open (first time only).
# ─────────────────────────────────────────────────────────────────────────────

# Change to the directory this script lives in (the project root)
cd "$(dirname "$0")"

# ── Check for Python 3.11+ ────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(sys.version_info[:2])" 2>/dev/null)
        major=$(echo "$version" | tr -d '(),' | awk '{print $1}')
        minor=$(echo "$version" | tr -d '(),' | awk '{print $2}')
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ] 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    osascript -e 'display dialog "vCard Studio needs Python 3.11 or later.\n\nGet it from:\nhttps://www.python.org/downloads/\n\nDownload the macOS installer, run it, then try again.\n\nDo NOT use Homebrew — it requires Xcode." buttons {"Open python.org", "Cancel"} default button "Open python.org" with icon caution' 2>/dev/null
    result=$?
    if [ $result -eq 0 ]; then
        open "https://www.python.org/downloads/"
    fi
    exit 1
fi

echo "Using Python: $($PYTHON --version)"

# ── Check / install dependencies ─────────────────────────────────────────────
MISSING=$("$PYTHON" -c "
missing = []
try: import vobject
except ImportError: missing.append('vobject')
try: import rapidfuzz
except ImportError: missing.append('rapidfuzz')
print(','.join(missing))
" 2>/dev/null)

if [ -n "$MISSING" ]; then
    echo "Installing missing dependencies: $MISSING"
    "$PYTHON" -m pip install --user vobject rapidfuzz phonenumbers 2>&1
    if [ $? -ne 0 ]; then
        osascript -e 'display dialog "Could not install dependencies automatically.\n\nPlease open Terminal and run:\n\npip3 install vobject rapidfuzz phonenumbers\n\nThen try again." buttons {"OK"} default button "OK" with icon stop' 2>/dev/null
        exit 1
    fi
fi

# ── Optional: phonenumbers ────────────────────────────────────────────────────
"$PYTHON" -c "import phonenumbers" 2>/dev/null || \
    "$PYTHON" -m pip install --user phonenumbers 2>/dev/null

# ── Launch ───────────────────────────────────────────────────────────────────
echo ""
echo "  Starting vCard Studio..."
echo "  Opening http://localhost:8421 in your browser."
echo ""
echo "  Press Ctrl-C in this window to stop."
echo ""

"$PYTHON" start-webui.py
