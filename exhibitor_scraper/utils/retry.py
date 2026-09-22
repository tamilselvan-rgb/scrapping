import asyncio
import logging
from functools import wraps
from typing import Callable, Any, TypeVar, Tuple

logger = logging.getLogger("scraper.retry")

T = TypeVar('T')

async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[type, ...] = (Exception,),
    **kwargs: Any
) -> Any:
    """
    Executes an async function with exponential backoff retry logic.
    """
    delay = initial_delay
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            # Check for HTTP status codes if it's an httpx.HTTPStatusError
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            
            # If it's an HTTPStatusError and not in our retryable list, don't retry (e.g. 400, 401, 403, 404)
            if status_code and status_code not in {429, 500, 502, 503, 504}:
                logger.error(f"Non-retryable HTTP status code {status_code} on attempt {attempt}/{retries}: {e}")
                raise e
                
            if attempt == retries:
                logger.error(f"Failed after {retries} attempts: {e}")
                raise e
                
            logger.warning(
                f"Attempt {attempt}/{retries} failed: {e}. "
                f"Retrying in {delay:.2f} seconds..."
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor

def retry_decorator(
    retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[type, ...] = (Exception,)
) -> Callable:
    """
    Decorator version of retry_async.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(
                func,
                *args,
                retries=retries,
                initial_delay=initial_delay,
                backoff_factor=backoff_factor,
                exceptions=exceptions,
                **kwargs
            )
        return wrapper
    return decorator
