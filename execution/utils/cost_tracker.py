from execution.db import get_connection

def log_api_cost(provider: str, model: str, input_tokens: int, output_tokens: int, task: str):
    """Calculate the estimated USD cost and save it to the DB."""
    
    # Pricing per 1k tokens (as of late 2024 / early 2025)
    PRICES = {
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "claude-3-5-haiku-20241022": {"input": 0.001, "output": 0.005},
        "gemini-2.0-flash-exp": {"input": 0.0, "output": 0.0} # Assuming free tier for now
    }
    
    cost = 0.0
    if model in PRICES:
        in_cost = (input_tokens / 1000) * PRICES[model]["input"]
        out_cost = (output_tokens / 1000) * PRICES[model]["output"]
        cost = in_cost + out_cost
        
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO api_usage (provider, model, input_tokens, output_tokens, cost_usd, task)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (provider, model, input_tokens, output_tokens, cost, task)
        )
        conn.commit()
    
    return cost
