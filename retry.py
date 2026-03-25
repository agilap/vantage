import asyncio
import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any


def with_retry(
	max_attempts: int = 3,
	base_delay: float = 1.0,
	exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
	"""Retry an async function with exponential backoff."""

	def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
		@wraps(func)
		async def wrapper(*args: Any, **kwargs: Any) -> Any:
			for attempt in range(max_attempts):
				try:
					return await func(*args, **kwargs)
				except exceptions as error:
					if attempt == max_attempts - 1:
						raise
					wait_time = base_delay * (2 ** attempt)
					print(
						"Retrying %s attempt %d/%d after error: %s. Waiting %.2fs"
						% (func.__name__, attempt + 1, max_attempts, error, wait_time)
					)
					await asyncio.sleep(wait_time)

		return wrapper

	return decorator


def safe_parse(response: Any, expected_type: str = "array") -> list | dict:
	"""Safely parse a JSON response payload from an OpenAI response object."""
	try:
		content = response.choices[0].message.content
	except (AttributeError, IndexError, TypeError):
		content = ""

	if content is None:
		content = ""

	content = str(content).strip()
	if content.startswith("```json"):
		content = content[7:]
	elif content.startswith("```"):
		content = content[3:]

	if content.endswith("```"):
		content = content[:-3]

	content = content.strip()

	try:
		parsed = json.loads(content)
		if expected_type == "object" and isinstance(parsed, dict):
			return parsed
		if expected_type == "array" and isinstance(parsed, list):
			return parsed
		return {} if expected_type == "object" else []
	except json.JSONDecodeError:
		print("Warning: Failed to parse JSON content: %s" % content)
		return {} if expected_type == "object" else []


async def call_openai(
	client: Any,
	system_prompt: str,
	user_prompt: str,
	max_tokens: int = 1000,
) -> Any:
	"""Send a standard chat completion request using gpt-4o-mini."""
	return await client.chat.completions.create(
		model="gpt-4o-mini",
		temperature=0.2,
		max_tokens=max_tokens,
		messages=[
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		],
	)
