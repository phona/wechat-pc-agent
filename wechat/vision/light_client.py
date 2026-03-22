"""Layer 2: Lightweight vision model via OpenAI-compatible API.

Calls a cheap/fast model (e.g. DeepSeek-OCR, PaddleOCR-VL) for text
recognition.  Same OpenAI chat-completions format as the heavy VLM.
"""

from __future__ import annotations

import base64
import json
import logging

logger = logging.getLogger(__name__)

OCR_PROMPT = """识别图片中的所有文字。

返回JSON格式：
[{"text": "识别的文字", "confidence": 0.95, "position": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}]

要求：
- 每个文字区域一个条目
- position是四个角的坐标（左上、右上、右下、左下）
- confidence是置信度(0-1)
- 如果没有文字，返回空数组 []
- 只返回JSON，不要其他内容"""


class LightClient:
    """Lightweight vision model client (OpenAI-compatible)."""

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        model: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def recognize(self, image_bytes: bytes) -> list[dict]:
        """Send image to lightweight model via OpenAI-compatible endpoint.

        Returns:
            List of {"text": str, "confidence": float, "position": list}
        """
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
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.0,
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
        return self._parse_response(content)

    def _parse_response(self, content: str) -> list[dict]:
        """Parse model response into structured results."""
        text = content.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return parsed.get("results", parsed.get("data", []))
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: treat each line as a text result
        results = []
        for i, line in enumerate(text.split("\n")):
            line = line.strip()
            if line:
                results.append({
                    "text": line,
                    "confidence": 0.8,
                    "position": [[0, i * 30]],
                })
        return results

    def recognize_text(self, image_bytes: bytes) -> tuple[str, float]:
        """Convenience: return (concatenated text, min confidence)."""
        results = self.recognize(image_bytes)
        if not results:
            return ("", 0.0)

        texts = []
        min_conf = 1.0
        for item in results:
            text = item.get("text", "")
            conf = item.get("confidence", item.get("score", 0.0))
            if text:
                texts.append(text)
                min_conf = min(min_conf, conf)

        return (" ".join(texts), min_conf if texts else 0.0)
