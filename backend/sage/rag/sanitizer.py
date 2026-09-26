import re

def sanitize_chunk(text: str) -> str:
    """
    Strip known prompt injection patterns from retrieved text.
    """
    if not text:
        return ""
        
    # Remove chat template tokens that might confuse the model
    tokens_to_remove = [
        "<|im_start|>", "<|im_end|>", 
        "<|system|>", "<|user|>", "<|assistant|>",
        "<s>", "</s>", 
        "[INST]", "[/INST]"
    ]
    
    sanitized = text
    for token in tokens_to_remove:
        sanitized = sanitized.replace(token, "")
        
    # Optional: regex for common prompt injection patterns
    # (e.g. "Ignore previous instructions", "System:")
    # For now, just removing the structural tokens is sufficient for 
    # preventing the chunk from taking over the chat template.
    
    return sanitized.strip()
