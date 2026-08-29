Write-Host "Downloading SAGE models via huggingface-cli..."
New-Item -ItemType Directory -Force -Path .\models | Out-Null

Write-Host "1. Downloading Qwen3-8B-Instruct (Reasoning/General - Primary)..."
huggingface-cli download Qwen/Qwen3-8B-GGUF --include "*Q4_K_M*" --local-dir .\models\

Write-Host "2. Downloading Gemma 4 12B IT (Coding/Vision - On-Demand)..."
huggingface-cli download unsloth/gemma-4-12b-it-GGUF --include "*Q4_K_M*" --local-dir .\models\

Write-Host ""
Write-Host "All models downloaded successfully to .\models\" -ForegroundColor Green
Write-Host ""
Write-Host "Model Stack (RTX 5060 8GB VRAM):" -ForegroundColor Cyan
Write-Host "  [PRIMARY]   Qwen3-8B       (~5GB) - Reasoning/General - auto-starts"
Write-Host "  [ON-DEMAND] Gemma 4 12B IT (~7.5GB) - Coding/Vision - swapped in when needed"
Write-Host ""
Write-Host "Only ONE model runs at a time. The SAGE router swaps them automatically." -ForegroundColor Yellow
