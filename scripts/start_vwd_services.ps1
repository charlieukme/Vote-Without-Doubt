# Vote Without Doubt (VWD) - Service Status Check and Hardhat Connection Manager

param(
    [switch]$AuthorizeRelayer
)

$ErrorActionPreference = "Continue"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "         VOTE WITHOUT DOUBT (VWD) - SYSTEM AND HARDHAT HEALTH CHECK             " -ForegroundColor Cyan
Write-Host "================================================================================`n" -ForegroundColor Cyan

$hardhatRpc = "http://127.0.0.1:8545"
$contractAddr = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
$expectedRelayer = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
$expectedOfficer = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# 1. Check Hardhat Node
Write-Host "[1/4] Checking Hardhat Blockchain Node ($hardhatRpc)..." -NoNewline
$nodeRunning = $false
try {
    $body = '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'
    $res = Invoke-RestMethod -Uri $hardhatRpc -Method Post -Body $body -ContentType "application/json" -TimeoutSec 2
    if ($res.result -eq "0x539" -or $res.result -eq "0x31337") {
        $nodeRunning = $true
        $chainIdDecimal = [Convert]::ToInt32($res.result, 16)
        Write-Host " [RUNNING]" -ForegroundColor Green
        Write-Host "      Detected Chain ID: $chainIdDecimal" -ForegroundColor Gray
    } else {
        Write-Host " [RUNNING - UNEXPECTED CHAIN $($res.result)]" -ForegroundColor Yellow
    }
} catch {
    Write-Host " [NOT RUNNING]" -ForegroundColor Red
}

# 2. Check Contract and Relayer Status
if ($nodeRunning) {
    Write-Host "[2/4] Checking EVotingBallotBox Contract ($contractAddr)..." -NoNewline
    try {
        $codeBody = '{"jsonrpc":"2.0","method":"eth_getCode","params":["' + $contractAddr + '", "latest"],"id":2}'
        $codeRes = Invoke-RestMethod -Uri $hardhatRpc -Method Post -Body $codeBody -ContentType "application/json" -TimeoutSec 2
        if ($codeRes.result -and $codeRes.result -ne "0x") {
            Write-Host " [DEPLOYED]" -ForegroundColor Green
            
            # Check relayer using hardhat check_contract.js
            Push-Location "blockchain"
            $checkOutput = (npx hardhat run scripts/check_contract.js --network localhost 2>$null) | Out-String
            Pop-Location
            
            if ($checkOutput -match "Contract Relayer:\s+(0x[a-fA-F0-9]{40})") {
                $actualRelayer = $matches[1]
                if ($actualRelayer.ToLower() -eq $expectedRelayer.ToLower()) {
                    Write-Host "      Relayer Account: $actualRelayer [AUTHORIZED]" -ForegroundColor Green
                } elseif ($actualRelayer -eq "0x0000000000000000000000000000000000000000") {
                    Write-Host "      Relayer Account: $actualRelayer [UNAUTHORIZED - ZERO ADDRESS]" -ForegroundColor Yellow
                    if ($AuthorizeRelayer) {
                        Write-Host "      Executing automatic relayer authorization..." -ForegroundColor Cyan
                        Push-Location "blockchain"
                        npx hardhat run scripts/authorize_relayer.js --network localhost
                        Pop-Location
                    } else {
                        Write-Host "      Run: cd blockchain; npx hardhat run scripts/authorize_relayer.js --network localhost" -ForegroundColor Yellow
                    }
                } else {
                    Write-Host "      Relayer Account: $actualRelayer [MISMATCH: expected $expectedRelayer]" -ForegroundColor Red
                }
            }
        } else {
            Write-Host " [NOT DEPLOYED]" -ForegroundColor Red
            Write-Host "      Deploy via: cd blockchain; npx hardhat run scripts/deploy.js --network localhost" -ForegroundColor Yellow
        }
    } catch {
        Write-Host " [QUERY ERROR]" -ForegroundColor Red
    }
} else {
    Write-Host "[2/4] EVotingBallotBox Check: Skipped (Hardhat node not running)" -ForegroundColor Gray
}

# 3. Check Flask Backend
Write-Host "[3/4] Checking Flask Backend (http://127.0.0.1:5000/api/health/ready)..." -NoNewline
try {
    $backendRes = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/health/ready" -Method Get -TimeoutSec 3
    Write-Host " [RUNNING]" -ForegroundColor Green
    if ($backendRes.runtime_config) {
        $backendContract = $backendRes.runtime_config.contract_address
        if ($backendContract -and $backendContract.ToLower() -eq $contractAddr.ToLower()) {
            Write-Host "      Runtime Contract Address: $backendContract [VERIFIED MATCH]" -ForegroundColor Green
        } else {
            Write-Host "      Runtime Contract Address: $backendContract [MISMATCH / NOT SET - Expected: $contractAddr]" -ForegroundColor Red
        }

        if ($backendRes.checks.relayer_authorized -eq $true) {
            Write-Host "      Backend Relayer Runtime: $($backendRes.checks.onchain_relayer) [VERIFIED AUTHORIZED ON-CHAIN]" -ForegroundColor Green
        } elseif ($backendRes.checks.relayer_error) {
            Write-Host "      Backend Relayer Error: $($backendRes.checks.relayer_error)" -ForegroundColor Red
        } else {
            Write-Host "      Backend Relayer Runtime: [AWAITING / NOT VERIFIED]" -ForegroundColor Yellow
        }
    }
} catch {
    # Fallback to basic health if ready fails
    try {
        $basicRes = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/health" -Method Get -TimeoutSec 2
        Write-Host " [RUNNING - BASIC HEALTH ONLY (RESTART NEEDED TO LOAD CONTRACT)]" -ForegroundColor Yellow
    } catch {
        Write-Host " [NOT RUNNING]" -ForegroundColor Red
    }
}

# 4. Check Frontend
Write-Host "[4/4] Checking Frontend Vite Dev Server (http://localhost:5173)..." -NoNewline
try {
    $feRes = Invoke-WebRequest -Uri "http://localhost:5173" -Method Get -TimeoutSec 2 -UseBasicParsing
    Write-Host " [RUNNING]" -ForegroundColor Green
} catch {
    Write-Host " [NOT RUNNING]" -ForegroundColor Yellow
}

Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host "         STANDARDIZED SERVICE STARTUP SEQUENCE (3 TERMINALS)                   " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "1. HARDHAT BLOCKCHAIN NODE:" -ForegroundColor White
Write-Host "   cd blockchain" -ForegroundColor Gray
Write-Host "   npx hardhat node`n" -ForegroundColor Yellow

Write-Host "2. FLASK BACKEND:" -ForegroundColor White
Write-Host "   python backend/run.py`n" -ForegroundColor Yellow

Write-Host "3. FRONTEND UI:" -ForegroundColor White
Write-Host "   npm --prefix frontend run dev`n" -ForegroundColor Yellow

Write-Host "OPTIONAL (if relayer requires re-authorization after node restart):" -ForegroundColor White
Write-Host "   cd blockchain" -ForegroundColor Gray
Write-Host "   npm run authorize:relayer`n" -ForegroundColor Yellow
Write-Host "================================================================================`n" -ForegroundColor Cyan
