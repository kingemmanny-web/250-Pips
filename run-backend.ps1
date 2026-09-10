$python = 'c:/Users/DELL/AppData/Local/Python/PYTHONCORE-3.14-64/python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

foreach ($name in @('BROKER', 'LIVE_TRADING_ENABLED', 'LIVE_TRADING_CONFIRMATION', 'MT5_LOGIN', 'MT5_PASSWORD', 'MT5_SERVER', 'MT5_PATH', 'MT5_SYMBOL_SUFFIX', 'MT5_VOLUME_PER_POSITION')) {
	$value = [Environment]::GetEnvironmentVariable($name, 'User')
	if ($null -ne $value) { Set-Item "Env:$name" $value }
}

& $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
