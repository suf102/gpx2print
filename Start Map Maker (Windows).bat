@echo off
setlocal
cd /d "%~dp0"
title Map Maker

echo Starting the map maker...
echo.

REM ---- find a Python we can use -------------------------------------------
REM Each candidate is tested by actually running it, so the Microsoft Store
REM placeholder python.exe (which does nothing and opens the Store) is skipped.
set "PY="
call :findpy py -3
if not defined PY call :findpy python
if not defined PY call :findpy python3
if not defined PY goto nopython

REM ---- make sure the libraries are there -----------------------------------
%PY% -c "import gpxpy,trimesh,shapely,matplotlib,numpy,scipy,PIL,manifold3d,mapbox_earcut" >nul 2>&1
if not errorlevel 1 goto run

echo First run - installing the libraries it needs.
echo This takes a couple of minutes, and only happens once.
echo.
%PY% -m pip install --quiet gpxpy trimesh shapely matplotlib numpy scipy pillow requests manifold3d mapbox_earcut
if not errorlevel 1 goto installed

echo That did not work, trying a different way...
%PY% -m pip install --quiet --user gpxpy trimesh shapely matplotlib numpy scipy pillow requests manifold3d mapbox_earcut
if errorlevel 1 goto nopip

:installed
echo Done.
echo.

REM ---- go ------------------------------------------------------------------
:run
%PY% -m gpx2print.gui
if errorlevel 1 goto failed
exit /b 0

:findpy
%* -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=%*"
goto :eof

:nopython
echo Python is not installed on this PC.
echo.
echo Install it from https://www.python.org/downloads/
echo.
echo IMPORTANT: on the first screen of the installer, tick
echo            "Add python.exe to PATH" before pressing Install.
echo.
echo Then double-click this file again.
echo.
pause
exit /b 1

:nopip
echo.
echo Could not install the libraries automatically.
echo Ask whoever set this up, or run this in Command Prompt:
echo     %PY% -m pip install -r "%CD%\requirements.txt"
echo.
pause
exit /b 1

:failed
echo.
echo The map maker closed with an error.
pause
exit /b 1
