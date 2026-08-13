#!/usr/bin/env bash
#
# ============================================================================
#  READING THIS IN A TEXT EDITOR? Then it opened instead of running. Here's why
#  and how to fix it — you have not done anything wrong.
#
#  THE QUICK WAY THAT ALWAYS WORKS
#    Right-click the folder this file is in, choose "Open in Terminal", then
#    type this and press return:
#
#        bash "Start Map Maker (Linux).sh"
#
#    That needs no permissions and no settings changed.
#
#  TO MAKE DOUBLE-CLICKING WORK INSTEAD
#    1. Right-click this file, choose Properties, open the Permissions tab and
#       tick "Allow executing file as program" (KDE calls it "Is executable").
#    2. On GNOME that is not enough by itself. Either right-click the file and
#       choose "Run as a Program", or open Files, go to
#       Preferences > General > Executable Text Files, and pick "Run them".
#
#  WHY IT HAPPENS
#    Downloading a single file from a website, or unpacking the zip with some
#    archive managers, drops the "may be run" flag. Using the .tar.gz instead
#    of the .zip usually keeps it.
# ============================================================================

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
is_conda() {
    "$1" -c 'import os,sys;raise SystemExit(0 if os.path.exists(os.path.join(sys.prefix,"conda-meta")) else 1)' \
        >/dev/null 2>&1
}

PY=""
NEWEST=""
NO_TK=""
for candidate in "$VENV/bin/python" python3 python3.13 python3.12 python3.11 \
                 python3.10 python /usr/bin/python3 /usr/bin/python3.13 \
                 /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    v=$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
    [ -z "$v" ] && continue
    [ -z "$NEWEST" ] && NEWEST="$v"
    "$candidate" -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,10) else 1)' \
        >/dev/null 2>&1 || continue
    # It must also be able to open a window. Checking this while choosing, rather
    # than after, matters: a conda Python usually has no tkinter, and no amount of
    # "apt install python3-tk" will give it one, because that installs tkinter for
    # the system Python instead. Skipping past it finds one that already works.
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
        echo "The Python in use is from Anaconda/conda ($NO_TK), and apt or dnf"
        echo "cannot add tkinter to it — those install it for the system Python,"
        echo "which is a different program. Do one of these instead:"
        echo
        echo "    conda install -y tk        (add it to this environment)"
        echo
        echo "or step out of conda and use the system Python:"
        echo
        echo "    conda deactivate"
        echo
        echo "then run this file again."
    else
        echo "On most distributions tkinter ships as its own package:"
        echo "    $(tk_hint)"
        echo
        echo "Then run this file again."
    fi
    echo
    read -r -p "Press return to close. "
    exit 1
fi

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
