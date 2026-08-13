#!/usr/bin/env bash
# Double-click this file to open the map maker, or run it from a terminal with
#   ./"Start Map Maker (Linux).sh"
#
# Most Linux file managers will not run a script on double-click until you allow
# it: right-click the file, open Properties, and tick something like
# "Allow executing file as program" (GNOME Files also has
# Preferences > Behaviour > Executable text files > Run them).

cd "$(dirname "$0")" || exit 1

VENV=".venv"
PKGS="gpxpy trimesh shapely matplotlib numpy scipy pillow requests manifold3d mapbox_earcut"
NEEDS="3.10"

echo "Starting the map maker…"
echo

# ---- what to type if a system package is missing -----------------------------
tk_hint() {
    local id=""
    [ -r /etc/os-release ] && . /etc/os-release && id="${ID:-}${ID_LIKE:-}"
    case "$id" in
        *debian*|*ubuntu*|*mint*) echo "sudo apt install python3-tk python3-venv" ;;
        *fedora*|*rhel*|*centos*) echo "sudo dnf install python3-tkinter" ;;
        *arch*|*manjaro*)         echo "sudo pacman -S tk" ;;
        *suse*)                   echo "sudo zypper install python3-tk" ;;
        *alpine*)                 echo "sudo apk add python3-tkinter" ;;
        *) echo "install your distribution's python3-tk (or python3-tkinter) package" ;;
    esac
}

venv_hint() {
    local id=""
    [ -r /etc/os-release ] && . /etc/os-release && id="${ID:-}${ID_LIKE:-}"
    case "$id" in
        *debian*|*ubuntu*|*mint*) echo "sudo apt install python3-venv" ;;
        *fedora*|*rhel*|*centos*) echo "sudo dnf install python3-virtualenv" ;;
        *) echo "install your distribution's python3-venv package" ;;
    esac
}

# ---- find a Python we can actually use ---------------------------------------
# Existing is not enough: Debian 11 and RHEL 8 still ship Python 3.9, which is too
# old for this program. Each candidate has to run AND be new enough.
PY=""
NEWEST=""
for candidate in "$VENV/bin/python" python3 python3.13 python3.12 python3.11 \
                 python3.10 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    v=$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
    [ -z "$v" ] && continue
    [ -z "$NEWEST" ] && NEWEST="$v"
    if "$candidate" -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,10) else 1)' \
        >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    if [ -n "$NEWEST" ]; then
        echo "The Python here is version $NEWEST, and this needs $NEEDS or newer."
        echo
        echo "Install a newer one with your package manager, for example:"
        echo "    sudo apt install python3.12 python3.12-tk python3.12-venv"
    else
        echo "Python 3 isn't installed."
        echo
        echo "Install it with your package manager, for example:"
        echo "    sudo apt install python3 python3-tk python3-venv"
    fi
    echo
    read -r -p "Press return to close. "
    exit 1
fi

# ---- tkinter is a separate package on most distributions ---------------------
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "Python is installed, but the graphical toolkit it needs is not."
    echo "On most distributions tkinter ships as its own package."
    echo
    echo "Install it with:"
    echo "    $(tk_hint)"
    echo
    echo "Then run this file again."
    echo
    read -r -p "Press return to close. "
    exit 1
fi

# ---- the libraries ------------------------------------------------------------
have_libs() {
    "$1" -c "import gpxpy,trimesh,shapely,matplotlib,numpy,scipy,PIL,manifold3d,mapbox_earcut" \
        >/dev/null 2>&1
}

if ! have_libs "$PY"; then
    echo "First run — installing the libraries it needs."
    echo "This takes a couple of minutes, and only happens once."
    echo

    # Try the plain install first. On Debian, Ubuntu, Fedora and friends this is
    # refused ("externally-managed-environment") to protect the system Python, so
    # fall back to a private virtual environment inside this folder.
    if ! "$PY" -m pip install --quiet --user $PKGS 2>/dev/null; then
        echo "Using a private environment in this folder instead…"
        if ! "$PY" -m venv "$VENV" 2>/dev/null; then
            echo
            echo "Could not create the environment. You probably need:"
            echo "    $(venv_hint)"
            echo
            read -r -p "Press return to close. "
            exit 1
        fi
        "$VENV/bin/python" -m pip install --quiet --upgrade pip
        if ! "$VENV/bin/python" -m pip install --quiet $PKGS; then
            echo
            echo "Couldn't install the libraries. Try this in a terminal:"
            echo "    $PY -m venv $VENV && $VENV/bin/pip install -r requirements.txt"
            echo
            read -r -p "Press return to close. "
            exit 1
        fi
        PY="$VENV/bin/python"
        # A venv built on the system Python normally inherits tkinter, but check.
        if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
            echo
            echo "The new environment cannot see tkinter. Install it system-wide:"
            echo "    $(tk_hint)"
            echo "then delete the $VENV folder and run this again."
            echo
            read -r -p "Press return to close. "
            exit 1
        fi
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
