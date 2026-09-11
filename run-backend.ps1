$python = Join-Path $PSScriptRoot '.venv-1\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$envFile = Join-Path $PSScriptRoot '.env'
$projectVariables = @('BROKER', 'LIVE_TRADING_ENABLED', 'LIVE_TRADING_CONFIRMATION', 'MT5_LOGIN', 'MT5_PASSWORD', 'MT5_SERVER', 'MT5_PATH', 'MT5_SYMBOL_SUFFIX', 'MT5_VOLUME_PER_POSITION', 'MT5_ACCOUNTS')
foreach ($name in $projectVariables) {
	Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
if (Test-Path $envFile) {
	foreach ($line in Get-Content $envFile) {
		$trimmed = $line.Trim()
		if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith('#')) { continue }
		$separator = $trimmed.IndexOf('=')
		if ($separator -lt 1) { continue }
		$name = $trimmed.Substring(0, $separator).Trim()
		$value = $trimmed.Substring($separator + 1).Trim()
		if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
			$value = $value.Substring(1, $value.Length - 2)
		}
		Set-Item "Env:$name" $value
	}
}

$bindHost = if ($env:HOST) { $env:HOST } else { '0.0.0.0' }
$port = if ($env:PORT) { $env:PORT } else { '8000' }
& $python -m uvicorn backend.app.main:app --host $bindHost --port $port
