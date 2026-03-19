"""
SecondMe API client
Wraps all SecondMe API calls with proper auth and error handling
"""
import os
import json
import requests
from typing import Generator


BASE_URL = os.getenv("SECONDME_BASE_URL", "https://app.mindos.com/gate/lab")


class SecondMeClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # ─── User Info ───────────────────────────────────────────────

    def get_user_info(self) -> dict:
        """Get basic user info (name, bio, selfIntroduction)"""
        resp = requests.get(
            f"{BASE_URL}/api/secondme/user/info",
            headers=self.headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data}")
        return data["data"]

    # ─── Soft Memory ─────────────────────────────────────────────

    def get_soft_memories(self, keyword: str = "", page_size: int = 100) -> list[dict]:
        """Get user's soft memories (personal knowledge base)"""
        params = {"pageNo": 1, "pageSize": page_size}
        if keyword:
            params["keyword"] = keyword

        resp = requests.get(
            f"{BASE_URL}/api/secondme/user/softmemory",
            headers=self.headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data}")
        return data["data"]["list"]

    def add_note(self, content: str, title: str = "") -> int:
        """Add a note/memory to user's Second Me"""
        payload = {"content": content, "memoryType": "TEXT"}
        if title:
            payload["title"] = title

        resp = requests.post(
            f"{BASE_URL}/api/secondme/note/add",
            headers=self.headers,
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data}")
        return data["data"]["noteId"]

    # ─── Chat (streaming) ─────────────────────────────────────────

    def chat_stream(
        self,
        message: str,
        session_id: str = None,
        system_prompt: str = None,
    ) -> Generator[str, None, None]:
        """
        Stream chat with user's Second Me avatar.
        Yields text chunks as they arrive.
        """
        payload = {"message": message}
        if session_id:
            payload["sessionId"] = session_id
        if system_prompt:
            payload["systemPrompt"] = system_prompt

        resp = requests.post(
            f"{BASE_URL}/api/secondme/chat/stream",
            headers=self.headers,
            json=payload,
            stream=True,
            timeout=60,
        )
        resp.raise_for_status()

        session_id_out = None
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("event:"):
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    parsed = json.loads(data_str)
                    # Capture session ID
                    if "sessionId" in parsed:
                        session_id_out = parsed["sessionId"]
                        continue
                    content = parsed["choices"][0]["delta"].get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError):
                    continue

    def chat_full(self, message: str, session_id: str = None, system_prompt: str = None) -> str:
        """Chat and collect full response as string"""
        return "".join(self.chat_stream(message, session_id, system_prompt))

    # ─── Act (structured JSON output) ─────────────────────────────

    def act_stream(
        self,
        message: str,
        action_control: str,
        session_id: str = None,
        system_prompt: str = None,
    ) -> dict:
        """
        Ask Second Me to make a structured JSON judgment.
        Returns parsed JSON dict.

        action_control must:
        - Be 20-8000 chars
        - Contain a JSON structure example
        - Include judgment rules and fallback
        """
        payload = {
            "message": message,
            "actionControl": action_control,
        }
        if session_id:
            payload["sessionId"] = session_id
        if system_prompt:
            payload["systemPrompt"] = system_prompt

        resp = requests.post(
            f"{BASE_URL}/api/secondme/act/stream",
            headers=self.headers,
            json=payload,
            stream=True,
            timeout=(10, 30),  # (connect, read-per-chunk) — prevents infinite stream hang
        )
        resp.raise_for_status()

        parts = []
        current_event = None

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("event: "):
                current_event = line[7:]
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    parsed = json.loads(data_str)
                    if current_event == "error":
                        raise RuntimeError(f"Act stream error: {parsed}")
                    if "sessionId" in parsed:
                        current_event = None
                        continue
                    content = parsed["choices"][0]["delta"].get("content", "")
                    if content:
                        parts.append(content)
                except (json.JSONDecodeError, KeyError):
                    continue
                current_event = None

        raw = "".join(parts).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            import re
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise RuntimeError(f"Could not parse act response as JSON: {raw}")
