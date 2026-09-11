$ErrorActionPreference = 'Stop'

function Set-EnvFileSetting($path, $name, $value) {
    $lines = if (Test-Path $path) { @(Get-Content $path) } else { @() }
    $pattern = '^' + [regex]::Escape($name) + '='
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match $pattern) {
            $found = $true
            "$name=$value"
        } else {
            $line
        }
    }
    if (-not $found) { $updated += "$name=$value" }
    Set-Content -Path $path -Value $updated -Encoding utf8
}

Write-Host 'Exness MT5 setup. Use a demo account first.'
$login = Read-Host 'Exness MT5 account login'
$passwordSecure = Read-Host 'Exness MT5 trading password' -AsSecureString
$server = Read-Host 'Exness MT5 server name'
$path = Read-Host 'Path to terminal64.exe (press Enter for automatic terminal discovery)'
$suffix = Read-Host 'Symbol suffix, if used by your Exness server (for example m)'
$volume = Read-Host 'Volume per position (default 0.01)'

$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($passwordSecure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
}

if ([string]::IsNullOrWhiteSpace($volume)) { $volume = '0.01' }
$envFile = Join-Path $PSScriptRoot '.env'
Set-EnvFileSetting $envFile 'BROKER' 'mt5'
Set-EnvFileSetting $envFile 'LIVE_TRADING_ENABLED' 'false'
Set-EnvFileSetting $envFile 'LIVE_TRADING_CONFIRMATION' ''
Set-EnvFileSetting $envFile 'MT5_LOGIN' $login
Set-EnvFileSetting $envFile 'MT5_PASSWORD' $password
Set-EnvFileSetting $envFile 'MT5_SERVER' $server
Set-EnvFileSetting $envFile 'MT5_PATH' $path
Set-EnvFileSetting $envFile 'MT5_SYMBOL_SUFFIX' $suffix
Set-EnvFileSetting $envFile 'MT5_VOLUME_PER_POSITION' $volume

Write-Host ''
Write-Host 'Exness MT5 settings saved to the project .env file.' -ForegroundColor Green
Write-Host 'Live trading remains disabled. Start the backend with .\run-backend.ps1 and check /api/broker/mt5/status.'
