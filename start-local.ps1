$projectRoot = $PSScriptRoot

Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'RemoteSigned', '-File', (Join-Path $projectRoot 'run-backend.ps1') -WorkingDirectory $projectRoot
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'npm run dev -- --host 127.0.0.1' -WorkingDirectory $projectRoot

Write-Host 'Backend:  http://127.0.0.1:8000'
Write-Host 'Frontend: http://127.0.0.1:5173'