$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .venv\Scripts\python.exe -m pip install 'pyinstaller>=6,<7'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --name MagnetLabel --paths src --add-data 'src/magnetlabel/static;magnetlabel/static' packaging/entry.py
if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed' }
Copy-Item -LiteralPath LICENSE -Destination dist/MagnetLabel/LICENSE.txt
Copy-Item -LiteralPath packaging/PORTABLE-README.txt -Destination dist/MagnetLabel/START-HERE.txt
& .venv\Scripts\python.exe packaging/license-notices.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
Compress-Archive -LiteralPath dist/MagnetLabel -DestinationPath dist/MagnetLabel-0.3.0-windows-x64.zip -Force
