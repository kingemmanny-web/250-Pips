$ErrorActionPreference = 'Stop'

function Set-UserSetting($name, $value) {
    [Environment]::SetEnvironmentVariable($name, $value, 'User')
    Set-Item "Env:$name" $value
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
Set-UserSetting 'BROKER' 'mt5'
Set-UserSetting 'LIVE_TRADING_ENABLED' 'false'
Set-UserSetting 'LIVE_TRADING_CONFIRMATION' ''
Set-UserSetting 'MT5_LOGIN' $login
Set-UserSetting 'MT5_PASSWORD' $password
Set-UserSetting 'MT5_SERVER' $server
Set-UserSetting 'MT5_PATH' $path
Set-UserSetting 'MT5_SYMBOL_SUFFIX' $suffix
Set-UserSetting 'MT5_VOLUME_PER_POSITION' $volume

Write-Host ''
Write-Host 'Exness MT5 settings saved to your Windows user environment.' -ForegroundColor Green
Write-Host 'Live trading remains disabled. Start the backend with .\run-backend.ps1 and check /api/broker/mt5/status.'
