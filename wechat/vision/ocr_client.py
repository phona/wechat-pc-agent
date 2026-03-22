"""Layer 2: PaddleOCR API client."""

from __future__ import annotations


class PaddleOCRClient:
    """Generic OCR API client. Works with any PaddleOCR-compatible service."""

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def recognize(self, image_bytes: bytes) -> list[dict]:
        """Send image to OCR API, return structured results.

        Returns:
            List of {"text": str, "confidence": float, "position": list}
        """
        import httpx

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._api_url}/ocr",
                files={"image": ("crop.png", image_bytes, "image/png")},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("results", data.get("data", []))

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
