#!/bin/bash
set -e

echo "Downloading SAGE models via huggingface-cli..."
mkdir -p ./models

echo "1. Downloading Qwen3-8B-Instruct (Reasoning/General)..."
huggingface-cli download Qwen/Qwen3-8B-GGUF --include "*Q4_K_M*" --local-dir ./models/

echo "2. Downloading Qwen3-Coder-8B (Coding)..."
huggingface-cli download Qwen/Qwen3-Coder-8B-GGUF --include "*Q4_K_M*" --local-dir ./models/

echo "3. Downloading Qwen2.5-VL-7B-Instruct (Vision)..."
huggingface-cli download Qwen/Qwen2.5-VL-7B-Instruct-GGUF --include "*Q4_K_M*" --local-dir ./models/

echo "All models downloaded successfully to ./models/"
