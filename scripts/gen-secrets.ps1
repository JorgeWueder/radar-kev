# Genera .env a partir de .env.example con secretos aleatorios. No sobrescribe un .env existente.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (Test-Path .env) { Write-Host ".env ya existe; no se modifica."; exit 0 }
function New-Secret([int]$bytes) {
  $b = New-Object byte[] $bytes
  [Security.Cryptography.RandomNumberGenerator]::Fill($b)
  ([Convert]::ToBase64String($b)).TrimEnd('=').Replace('+','-').Replace('/','_')
}
$lines = Get-Content .env.example
$simple = 'POSTGRES_SUPERUSER_PASSWORD','RADAR_DB_PASSWORD','N8N_DB_PASSWORD','LANGFLOW_DB_PASSWORD','RADAR_SERVICE_KEY','N8N_ENCRYPTION_KEY','LANGFLOW_SUPERUSER_PASSWORD'
$out = foreach ($l in $lines) {
  if ($l -like 'LANGFLOW_SECRET_KEY=*') { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Fill($b); "LANGFLOW_SECRET_KEY=$([Convert]::ToBase64String($b).Replace('+','-').Replace('/','_'))"; continue }
  $k = ($l -split '=')[0]
  if ($simple -contains $k) { "$k=$(New-Secret 24)" }
  elseif ($k -eq 'JWT_SECRET') { "$k=$(New-Secret 48)" }
  elseif ($k -eq 'FERNET_KEY') {
    $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Fill($b)
    "$k=$([Convert]::ToBase64String($b).Replace('+','-').Replace('/','_'))"
  } else { $l }
}
$out | Set-Content .env -Encoding utf8
Write-Host ".env generado con secretos aleatorios."
