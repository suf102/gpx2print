#!/bin/bash
# Double-click this file to open the map maker.
# It checks that the bits it needs are installed, then opens the window.

cd "$(dirname "$0")" || exit 1

VENV=".venv"
PKGS="gpxpy trimesh shapely matplotlib numpy scipy pillow requests manifold3d mapbox_earcut"
NEEDS="3.10"

echo "Starting the map maker…"
echo

# ---- find a Python we can actually use ---------------------------------------
# Existing is not enough: macOS ships Python 3.9 at /usr/bin/python3, which is too
# old for this program. Each candidate has to run AND be new enough.
is_conda() {
    "$1" -c 'import os,sys;raise SystemExit(0 if os.path.exists(os.path.join(sys.prefix,"conda-meta")) else 1)' \
        >/dev/null 2>&1
}

PY=""
NEWEST=""
NO_TK=""
for candidate in "$VENV/bin/python" python3 python3.13 python3.12 python3.11 \
                 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                 /usr/bin/python3 "$HOME/anaconda3/bin/python3"; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    v=$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
    [ -z "$v" ] && continue
    [ -z "$NEWEST" ] && NEWEST="$v"
    "$candidate" -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,10) else 1)' \
        >/dev/null 2>&1 || continue
    # It must also be able to open a window. A conda Python often cannot, and
    # nothing installed system-wide will fix that one, so skip past it.
    if "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
    [ -z "$NO_TK" ] && NO_TK="$candidate"
done

if [ -z "$PY" ] && [ -n "$NO_TK" ]; then
    echo "Python is installed, but it cannot open a window: it has no tkinter."
    echo
    if is_conda "$NO_TK"; then
        echo "The Python in use is from Anaconda/conda. Add the toolkit to it with:"
        echo
        echo "    conda install -y tk"
        echo
        echo "or step out of conda and use another Python:"
        echo
        echo "    conda deactivate"
        echo
        echo "then double-click this file again."
    else
        echo "Install Python from https://www.python.org/downloads/, which includes"
        echo "the toolkit, then double-click this file again."
    fi
    echo
    read -r -p "Press return to close. "
    exit 1
fi

if [ -z "$PY" ]; then
    if [ -n "$NEWEST" ]; then
        echo "The Python on this Mac is version $NEWEST, and this needs $NEEDS or newer."
        echo "(macOS includes an old Python of its own, which is why this happens.)"
    else
        echo "Python isn't installed on this Mac."
    fi
    echo
    echo "Get a current version from https://www.python.org/downloads/"
    echo "(the big yellow Download button), then double-click this file again."
    echo
    read -r -p "Press return to close. "
    exit 1
fi

# ---- make sure the libraries are there ----------------------------------------
have_libs() {
    "$1" -c "import gpxpy,trimesh,shapely,matplotlib,numpy,scipy,PIL,manifold3d,mapbox_earcut" \
        >/dev/null 2>&1
}

if ! have_libs "$PY"; then
    echo "First run — installing the libraries it needs."
    echo "This takes a couple of minutes, and only happens once."
    echo

    # Homebrew and python.org builds mark themselves "externally managed" and
    # refuse to install into themselves, so fall back to a private environment
    # inside this folder.
    if ! "$PY" -m pip install --quiet $PKGS 2>/dev/null \
       && ! "$PY" -m pip install --quiet --user $PKGS 2>/dev/null; then
        echo "Using a private environment in this folder instead…"
        if ! "$PY" -m venv "$VENV" 2>/dev/null \
           || ! "$VENV/bin/python" -m pip install --quiet --upgrade pip 2>/dev/null \
           || ! "$VENV/bin/python" -m pip install --quiet $PKGS; then
            echo
            echo "Couldn't install the libraries automatically."
            echo "Ask whoever set this up, or run this in Terminal:"
            echo "    $PY -m venv \"$(pwd)/$VENV\""
            echo "    \"$(pwd)/$VENV/bin/pip\" install -r \"$(pwd)/requirements.txt\""
            echo
            read -r -p "Press return to close. "
            exit 1
        fi
        PY="$VENV/bin/python"
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
