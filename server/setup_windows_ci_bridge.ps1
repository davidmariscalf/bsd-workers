param(
    [string]$Root = "C:\bsd-mcp"
)

$ErrorActionPreference = "Stop"
$WorkersRoot = Join-Path $Root "bsd-workers-bridge"
$SecretsPath = Join-Path $Root "bsd_ci_secrets.json"
$LoaderPath = Join-Path $Root "load_bsd_ci_env.ps1"
$DispatchPath = Join-Path $WorkersRoot "provider_dispatch.py"
$TasksPath = Join-Path $WorkersRoot "server-self-test.json"

Write-Host "=== BSD GitHub + GitLab server bridge setup ==="
Write-Host "Root: $Root"

if (-not (Test-Path $Root)) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
}
if (-not (Test-Path $WorkersRoot)) {
    New-Item -ItemType Directory -Path $WorkersRoot -Force | Out-Null
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python was not found in PATH. The BSD server already normally uses Python; open the same user/session that runs it."
}

Write-Host "Downloading the current provider dispatcher from GitHub..."
Invoke-WebRequest `
    -Uri "https://raw.githubusercontent.com/davidmariscalf/bsd-workers/main/provider_dispatch.py" `
    -OutFile $DispatchPath `
    -UseBasicParsing

$taskJson = @'
[
  {"id":"server-bridge-self-test","type":"self_test","params":{}}
]
'@
Set-Content -Path $TasksPath -Value $taskJson -Encoding UTF8

Write-Host ""
Write-Host "Paste the GitHub fine-grained token when prompted. It will NOT be shown."
$gh = Read-Host "GitHub token" -AsSecureString
Write-Host "Paste the GitLab project/personal access token when prompted. It will NOT be shown."
$gl = Read-Host "GitLab token" -AsSecureString

function Protect-MachineSecureString([Security.SecureString]$Secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    $bytes = $null
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $bytes = [Text.Encoding]::UTF8.GetBytes($plain)
        $protected = [Security.Cryptography.ProtectedData]::Protect(
            $bytes,
            $null,
            [Security.Cryptography.DataProtectionScope]::LocalMachine
        )
        return [Convert]::ToBase64String($protected)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        if ($bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
    }
}

# Machine-scoped Windows DPAPI: SYSTEM and the interactive administrator can
# decrypt on this same Windows machine, provided the ACL grants file access.
$cfg = [ordered]@{
    github_token_machine_enc = Protect-MachineSecureString $gh
    gitlab_token_machine_enc = Protect-MachineSecureString $gl
    github_repo              = "davidmariscalf/bsd-workers"
    gitlab_project           = "86129510"
    gitlab_ref               = "main"
    created_at_utc           = [DateTime]::UtcNow.ToString("o")
}
$cfg | ConvertTo-Json | Set-Content -Path $SecretsPath -Encoding UTF8

$loader = @'
$ErrorActionPreference = "Stop"
$cfg = Get-Content "C:\bsd-mcp\bsd_ci_secrets.json" -Raw | ConvertFrom-Json

function Unprotect-MachineSecret([string]$Encrypted) {
    $protected = [Convert]::FromBase64String($Encrypted)
    $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
        $protected,
        $null,
        [Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    try {
        return [Text.Encoding]::UTF8.GetString($plainBytes)
    }
    finally {
        [Array]::Clear($plainBytes, 0, $plainBytes.Length)
    }
}

$env:BSD_GITHUB_TOKEN = Unprotect-MachineSecret ([string]$cfg.github_token_machine_enc)
$env:BSD_GITHUB_REPO = [string]$cfg.github_repo
$env:BSD_GITLAB_TOKEN = Unprotect-MachineSecret ([string]$cfg.gitlab_token_machine_enc)
$env:BSD_GITLAB_PROJECT = [string]$cfg.gitlab_project
$env:BSD_GITLAB_REF = [string]$cfg.gitlab_ref
'@
Set-Content -Path $LoaderPath -Value $loader -Encoding UTF8

# Restrict the encrypted secret file to this user, SYSTEM and local Administrators.
try {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    icacls $SecretsPath /inheritance:r /grant:r "${me}:(F)" "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" | Out-Null
} catch {
    Write-Warning "Could not tighten ACLs automatically: $($_.Exception.Message)"
}

. $LoaderPath

Write-Host ""
Write-Host "Testing GitHub dispatch..."
& python $DispatchPath github $TasksPath
if ($LASTEXITCODE -ne 0) {
    throw "GitHub dispatch test failed. Check the token permissions and repository selection."
}

Write-Host ""
Write-Host "Testing GitLab dispatch..."
& python $DispatchPath gitlab $TasksPath
if ($LASTEXITCODE -ne 0) {
    throw "GitLab dispatch test failed. Check token scope/role and project access."
}

Write-Host ""
Write-Host "=== BRIDGE AUTHENTICATION TESTS DISPATCHED ==="
Write-Host "Machine-encrypted secrets: $SecretsPath"
Write-Host "Environment loader: $LoaderPath"
Write-Host "Dispatcher: $DispatchPath"
Write-Host ""
Write-Host "Important: credentials are encrypted with Windows DPAPI LocalMachine so the SYSTEM controller can load them on this machine."
Write-Host "The existing bsd_lab_controller_v3.py still needs its queue routing/result collection patch before production tasks are sent automatically."
