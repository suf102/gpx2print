#!/bin/bash
# Double-click this file to open the map maker.
# It checks that the bits it needs are installed, then opens the window.

cd "$(dirname "$0")" || exit 1

echo "Starting the map maker…"
echo

# ---- find a Python we can use -------------------------------------------------
PY=""
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                 /usr/bin/python3 "$HOME/anaconda3/bin/python3"; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "Python isn't installed on this Mac."
    echo
    echo "Install it from https://www.python.org/downloads/ "
    echo "(the big yellow Download button), then double-click this file again."
    echo
    read -r -p "Press return to close. "
    exit 1
fi

# ---- make sure the libraries are there ----------------------------------------
if ! "$PY" - <<'CHECK' >/dev/null 2>&1
import importlib, sys
for m in ("gpxpy","trimesh","shapely","matplotlib","numpy","scipy","PIL",
          "manifold3d","mapbox_earcut"):
    importlib.import_module(m)
CHECK
then
    echo "First run — installing the libraries it needs."
    echo "This takes a couple of minutes, and only happens once."
    echo
    if ! "$PY" -m pip install --quiet gpxpy trimesh shapely matplotlib numpy scipy \
                                      pillow requests manifold3d mapbox_earcut; then
        echo "That didn't work, trying a different way…"
        "$PY" -m pip install --quiet --user gpxpy trimesh shapely matplotlib numpy \
                                            scipy pillow requests manifold3d \
                                            mapbox_earcut || {
            echo
            echo "Couldn't install the libraries automatically."
            echo "Ask whoever set this up, or run this in Terminal:"
            echo "    $PY -m pip install -r \"$(pwd)/requirements.txt\""
            echo
            read -r -p "Press return to close. "
            exit 1
        }
    fi
    echo "Done."
    echo
fi

# ---- go -----------------------------------------------------------------------
"$PY" -m gpx2print.gui
STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo
    echo "The map maker closed with an error (code $STATUS)."
    read -r -p "Press return to close. "
fi
