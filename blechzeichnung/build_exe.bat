@echo off
rem Erstellt dist\Blechzeichnung.exe (Windows, Python 3.10+ muss installiert sein)
cd /d %~dp0
python -m pip install --upgrade ezdxf pyinstaller || goto :fehler
python -m PyInstaller --noconfirm --onefile --windowed --name Blechzeichnung blech.py || goto :fehler
echo.
echo Fertig: %~dp0dist\Blechzeichnung.exe
pause
exit /b 0
:fehler
echo Build fehlgeschlagen.
pause
exit /b 1
