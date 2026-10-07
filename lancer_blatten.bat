@echo off
setlocal
cd /d "%~dp0"
rem Raccourci Windows: lance "python blatten.py menu". Cherche Python (py, python) puis celui fourni avec Blender.
rem La fenetre reste ouverte a la fin pour que les messages d'erreur restent lisibles.
where py >nul 2>nul && (py -3 blatten.py menu & goto fin)
where python >nul 2>nul && (python blatten.py menu & goto fin)
for /d %%B in ("%ProgramFiles%\Blender Foundation\Blender *" "F:\Program Files (x86)\Blender") do (
  for /d %%V in ("%%~B\*") do (
    if exist "%%~V\python\bin\python.exe" (
      "%%~V\python\bin\python.exe" blatten.py menu
      goto fin
    )
  )
)
echo Python introuvable. Installez-le (winget install Python.Python.3.12) puis relancez ce fichier.
:fin
echo.
pause
endlocal
