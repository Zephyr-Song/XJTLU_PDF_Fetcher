@echo off
rem Remove the Mark-of-the-Web flag from the exe in this folder.
rem The flag is added by browsers when a file is downloaded from the internet,
rem and it is what triggers the "Windows protected your PC" SmartScreen prompt.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%~dp0' -Filter *.exe -File | ForEach-Object { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue }" >nul 2>&1
echo.
echo  Done. The download block has been removed.
echo  You can now double-click XJTLU_PDF_Fetcher.exe
echo.
pause
