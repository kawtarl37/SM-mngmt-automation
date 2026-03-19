from openai import OpenAI
from pydantic import BaseModel
from execution.config import OPENAI_API_KEY, TEXT_PREFERENCE_MODEL
from execution.utils.cost_tracker import log_api_cost
from execution.utils.logger import setup_logger

logger = setup_logger("llm_client")

class LLMClient:
    def __init__(self):
        # Initialize OpenAI client 
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = TEXT_PREFERENCE_MODEL

    def generate_structured(self, system_prompt: str, user_prompt: str, response_format: type[BaseModel], task_name: str = "general") -> BaseModel:
        """
        Send a prompt to the LLM and return a strictly typed Pydantic object.
        Automatically tracks token usage and logs the cost.
        """
        logger.info(f"Calling {self.model} for task: {task_name}")
        
        try:
            completion = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format=response_format
            )
            
            # Extract response and token usage
            parsed_response = completion.choices[0].message.parsed
            usage = completion.usage
            
            # Log cost
            cost = log_api_cost(
                provider="openai",
                model=self.model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                task=task_name
            )
            
            logger.info(f"LLM call successful. Cost: ${cost:.4f}")
            return parsed_response
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}", exc_info=True)
            raise
