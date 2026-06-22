[CmdletBinding(PositionalBinding = $false)]
param(
  [string]$Python = "",
  [string]$StateDir = ".openclaw-loop",
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$ForwardArgs
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "openclaw_loop.py"

if (-not (Test-Path -LiteralPath $scriptPath)) {
  throw "Cannot find openclaw_loop.py at $scriptPath"
}

if ($Python) {
  & $Python $scriptPath --state-dir $StateDir @ForwardArgs
  exit $LASTEXITCODE
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
  & python $scriptPath --state-dir $StateDir @ForwardArgs
  exit $LASTEXITCODE
}

$pyCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pyCommand) {
  & py -3 $scriptPath --state-dir $StateDir @ForwardArgs
  exit $LASTEXITCODE
}

throw @"
No Python launcher found.

Try one of these:
1. Install Python 3 and enable "Add python.exe to PATH".
2. Use the Windows Python launcher command if available:
   py -3 "$scriptPath" --state-dir "$StateDir" <command>
3. Pass an explicit Python path:
   powershell -ExecutionPolicy Bypass -File "$PSCommandPath" -Python "C:\Path\To\python.exe" -StateDir "$StateDir" <command>
"@
