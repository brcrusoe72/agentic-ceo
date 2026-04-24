"""Shared API client routed through OpenClaw gateway — no API key needed."""

import json
import subprocess
import time
import uuid


def get_api_key() -> str:
    """Legacy stub — no longer needed since we route through OpenClaw gateway.
    Returns a placeholder so existing imports don't break."""
    return "routed-via-openclaw-gateway"


def call_claude(system: str, user: str, model: str = "claude-sonnet-4-5-20250929", max_tokens: int = 8192) -> str:
    """Call Claude via OpenClaw gateway. Uses subscription auth, no API key required.
    
    Routes through `openclaw agent` CLI which handles auth internally.
    System prompt is prepended to the user message since openclaw agent
    doesn't have a separate system prompt parameter.
    """
    # Combine system + user into a single prompt
    prompt = f"""<system_instructions>
{system}
</system_instructions>

{user}"""

    session_id = f"ceo-{uuid.uuid4().hex[:8]}"
    
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(
                [
                    "openclaw", "agent",
                    "--session-id", session_id,
                    "--message", prompt,
                    "--json",
                    "--timeout", "600",
                ],
                capture_output=True,
                text=True,
                timeout=660,
            )
            
            if result.returncode != 0:
                stderr = result.stderr.strip()
                print(f"⚠️ openclaw agent failed (attempt {attempt}/{max_attempts}): {stderr[:200]}")
                if attempt == max_attempts:
                    raise RuntimeError(f"openclaw agent failed after {max_attempts} attempts: {stderr[:500]}")
                time.sleep(5 * attempt)
                continue
            
            # Parse JSON response
            data = json.loads(result.stdout)
            
            # Extract reply text from response
            if "result" in data and "payloads" in data["result"]:
                payloads = data["result"]["payloads"]
                if payloads and payloads[0].get("text"):
                    return payloads[0]["text"]
            
            # Fallback: try other response shapes
            if "reply" in data:
                return data["reply"]
            if "text" in data:
                return data["text"]
            
            print(f"⚠️ Unexpected response shape (attempt {attempt}/{max_attempts}): {list(data.keys())}")
            if attempt == max_attempts:
                raise RuntimeError(f"Could not extract text from openclaw response: {json.dumps(data)[:500]}")
            time.sleep(5 * attempt)
            
        except subprocess.TimeoutExpired:
            print(f"⚠️ Timeout (attempt {attempt}/{max_attempts})")
            if attempt == max_attempts:
                raise RuntimeError("openclaw agent timed out after 360s")
            time.sleep(10)
            
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parse error (attempt {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts:
                raise RuntimeError(f"Could not parse openclaw response as JSON: {result.stdout[:500]}")
            time.sleep(5 * attempt)
    
    raise RuntimeError("API retry loop exhausted")
