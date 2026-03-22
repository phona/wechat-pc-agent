"""Layer 3: VLM client and prompt templates."""

from __future__ import annotations

import base64
import json
import logging

logger = logging.getLogger(__name__)


class VLMClient:
    """OpenAI-compatible VLM API client."""

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        model: str = "Qwen/Qwen3-VL-8B-Instruct",
        timeout: float = 30.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def call_sync(self, prompt: str, image_bytes: bytes) -> str:
        """Send an image + prompt to the VLM and return the text response."""
        import httpx

        b64 = base64.b64encode(image_bytes).decode("ascii")

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
        }

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._api_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return content

    def parse_json_response(self, response: str) -> dict:
        """Extract JSON from a VLM response that may contain markdown fences."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return json.loads(text)


# ---------------------------------------------------------------------------
# VLM prompt templates
# ---------------------------------------------------------------------------

CALIBRATION_PROMPT = """You are analyzing a fullscreen WeChat (Weixin) desktop screenshot.
Image resolution: {width}x{height}px.

Identify the pixel coordinates of these UI elements, list visible chats with
their bounding boxes, and identify the message display area.

Return ONLY valid JSON in this exact format (no other text):
{{
  "elements": {{
    "search_box": {{"x": int, "y": int, "w": int, "h": int}},
    "chat_list_area": {{"x": int, "y": int, "w": int, "h": int}},
    "input_box": {{"x": int, "y": int, "w": int, "h": int}},
    "message_area": {{"x": int, "y": int, "w": int, "h": int}}
  }},
  "visible_chats": [
    {{"name": "chat name", "has_unread": true, "unread_count": null, "position_y": int}}
  ],
  "chat_row_height": int,
  "active_chat": null
}}

Notes:
- search_box: the search field at the top of the left sidebar
- chat_list_area: the entire left sidebar containing chat entries
- input_box: the message input area at the bottom of the right panel
- message_area: the scrollable area where chat messages appear (right panel, above input box)
- chat_row_height: the uniform height of each chat row in pixels
- position_y: the vertical center of each chat entry relative to the window
- has_unread: true if there is a red dot or unread count badge
- unread_count: the number shown on the badge, or null if just a dot"""

SIDEBAR_READ_PROMPT = """You are analyzing a WeChat desktop screenshot.
Previous UI state:
{prev_state}

Look at the left sidebar chat list. Identify ALL chats and their unread status.

Return ONLY valid JSON:
{{
  "visible_chats": [
    {{"name": "chat name", "has_unread": true, "unread_count": null, "position_y": int}}
  ],
  "changes": "brief description of what changed"
}}"""

CHAT_READ_PROMPT = """You are analyzing a WeChat desktop screenshot showing the chat with "{chat_name}".
The last message I already processed had content starting with: "{last_seen_msg}"

List ALL messages that appear AFTER that last processed message.
If last_seen_msg is empty, list all visible messages.

Return ONLY valid JSON:
{{
  "messages": [
    {{"sender": "name", "content": "full message text", "is_self": false}}
  ]
}}

Notes:
- sender: the name of the person who sent the message
- is_self: true if the message was sent by the logged-in user
- content: the full text of the message
- Include ALL new messages, not just the latest one"""

IMAGE_DESCRIBE_PROMPT = """You are analyzing a cropped image from a WeChat chat message.
Describe the content of this image briefly in Chinese.
If it contains text, include the text.
If it's a photo, describe what's in the photo.
Return a plain text description, no JSON needed."""
