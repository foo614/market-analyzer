"""
LLM Router for ClawdBot System.
Manages primary (Gemini 2.5 Flash) and fallback (Ollama) execution, handling rate limits.
"""
import os
import sys
import time
import json
import hashlib
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    get_gemini_api_keys, GEMINI_MODEL, GEMINI_RPM_LIMIT, GEMINI_RPD_LIMIT,
    OPENROUTER_MODEL, OLLAMA_API_URL, OLLAMA_MODEL, check_ollama_health, get_credential
)
from logger import get_logger

log = get_logger("LLMRouter")

try:
    from google import genai
    from google.genai import types
except ImportError:
    log.error("google-genai not installed. Please pip install google-genai")
    genai = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Rate limiting state file
TRACKER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_tracker.json")

class LLMRouter:
    def __init__(self):
        self.openai_key = get_credential('openai_key')
        self.openrouter_key = get_credential('openrouter_key', 'OPENROUTER_API_KEY')
        self.nvidia_key = get_credential('nvidia_key')

        if genai and get_gemini_api_keys():
            log.info(f"Gemini enabled ({GEMINI_MODEL})")
        elif genai:
            log.warning("Gemini keys not configured.")

        if self.openai_key and OpenAI:
            log.info("OpenAI High-Tier Client enabled (gpt-4o)")
            self.openai_real_client = OpenAI(api_key=self.openai_key)
        else:
            self.openai_real_client = None

        if self.openrouter_key and OpenAI:
            log.info(f"OpenRouter Client enabled ({OPENROUTER_MODEL})")
            self.openrouter_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.openrouter_key,
            )
        else:
            self.openrouter_client = None

        if self.nvidia_key and OpenAI:
            log.info("NVIDIA Mid-Tier Client enabled (meta/llama-3.1-405b-instruct)")
            self.nvidia_client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.nvidia_key
            )
        else:
            self.nvidia_client = None

        self.ollama_client = None
        ollama_ok, msg = check_ollama_health()
        if ollama_ok and OpenAI:
            try:
                self.ollama_client = OpenAI(base_url=OLLAMA_API_URL, api_key="ollama")
                log.info(f"Ollama Fallback Client initialized ({OLLAMA_MODEL})")
            except Exception as e:
                log.warning(f"Ollama client init failed: {e}")

        self.state = self._load_state()

    def _fp(self, key):
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    def _load_state(self):
        default_state = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "keys": {}
        }
        if os.path.exists(TRACKER_FILE):
            try:
                with open(TRACKER_FILE, "r") as f:
                    state = json.load(f)
                
                # Reset if new day
                if state.get("date", "") != datetime.now().strftime("%Y-%m-%d"):
                    state = default_state

                if "keys" not in state:
                    state = default_state

                now = time.time()
                for fp, ks in state.get("keys", {}).items():
                    ks["requests_this_minute"] = [t for t in ks.get("requests_this_minute", []) if now - t < 60]
                return state
            except Exception:
                pass
        return default_state

    def _save_state(self):
        try:
            with open(TRACKER_FILE, "w") as f:
                json.dump(self.state, f)
        except Exception:
            pass

    def _get_key_state(self, fp):
        keys = self.state.setdefault("keys", {})
        if fp not in keys:
            keys[fp] = {
                "daily_requests": 0,
                "requests_this_minute": [],
                "suspended_until": 0
            }
        return keys[fp]

    def _can_use_key(self, fp):
        now = time.time()
        ks = self._get_key_state(fp)

        if ks.get("suspended_until", 0) > now:
            wait_s = ks["suspended_until"] - now
            return False, f"Suspended ({int(wait_s)}s remaining)"

        if ks.get("daily_requests", 0) >= GEMINI_RPD_LIMIT:
            return False, "Daily limit reached"

        ks["requests_this_minute"] = [t for t in ks.get("requests_this_minute", []) if now - t < 60]
        
        if len(ks["requests_this_minute"]) >= GEMINI_RPM_LIMIT:
            return False, "Minute limit reached"

        return True, "OK"

    def _record_gemini_request(self, fp):
        ks = self._get_key_state(fp)
        ks["daily_requests"] = ks.get("daily_requests", 0) + 1
        ks["requests_this_minute"].append(time.time())
        self._save_state()

    def _select_key(self, exclude_fps=None):
        gemini_keys = get_gemini_api_keys()
        if not genai or not gemini_keys:
            return None, None, "Not initialized"

        exclude_fps = set(exclude_fps or [])
        for key in gemini_keys:
            fp = self._fp(key)
            if fp in exclude_fps:
                continue
            can_use, reason = self._can_use_key(fp)
            if can_use:
                return key, fp, "OK"
        return None, None, "All keys limited/suspended"

    def route_request(self, prompt, expect_json=False, agent_name="Agent"):
        """
        Attempts to route the request to Gemini. 
        If limits hit or API fails, auto-falls back to Ollama.
        """
        raw_text = None
        source = None

        used_fps = []
        for attempt in range(2):
            key, fp, reason = self._select_key(exclude_fps=used_fps)
            if not key:
                if attempt == 0:
                    log.debug(f"Gemini skipped: {reason}. Falling back to Ollama.")
                break

            used_fps.append(fp)
            try:
                ks = self._get_key_state(fp)
                current_rpm = len(ks["requests_this_minute"])
                log.info(f"{agent_name} -> Gemini ({current_rpm + 1}/{GEMINI_RPM_LIMIT} RPM)")

                client = genai.Client(api_key=key)
                config = types.GenerateContentConfig(temperature=0.2)
                if expect_json:
                    config.response_mime_type = "application/json"

                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=config
                )
                raw_text = response.text
                source = "Gemini"
                self._record_gemini_request(fp)
                break
            except Exception as e:
                err_str = str(e).lower()
                log.warning(f"Gemini generation failed: {e}")
                if "429" in err_str or "quota" in err_str or "exhausted" in err_str or "rate" in err_str:
                    ks = self._get_key_state(fp)
                    ks["suspended_until"] = time.time() + 60
                    self._save_state()
                    continue
                break

        # --- OPENROUTER FALLBACK ---
        if not raw_text and self.openrouter_client:
            log.info(f"{agent_name} -> OpenRouter ({OPENROUTER_MODEL})")
            try:
                response = self.openrouter_client.chat.completions.create(
                    model=OPENROUTER_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=300,
                    response_format={"type": "json_object"} if expect_json else None
                )
                raw_text = response.choices[0].message.content
                source = "OpenRouter"
            except Exception as e:
                log.warning(f"OpenRouter fallback failed: {e}")

        # --- OPENAI FALLBACK ---
        if not raw_text and self.openai_real_client:
            log.info(f"{agent_name} -> OpenAI (gpt-4o)")
            try:
                response = self.openai_real_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=300,
                    response_format={"type": "json_object"} if expect_json else None
                )
                raw_text = response.choices[0].message.content
                source = "OpenAI"
            except Exception as e:
                log.warning(f"OpenAI fallback failed: {e}")

        # --- NVIDIA FALLBACK ---
        if not raw_text and self.nvidia_client:
            log.info(f"{agent_name} -> NVIDIA (Llama 3.1)")
            try:
                response = self.nvidia_client.chat.completions.create(
                    model="meta/llama-3.1-405b-instruct",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=300
                )
                raw_text = response.choices[0].message.content
                source = "NVIDIA"
            except Exception as e:
                log.warning(f"NVIDIA fallback failed: {e}")

        # --- OLLAMA FALLBACK ---
        if not raw_text:
            if not self.ollama_client:
                return None, "No LLM available (Gemini skipped/failed, Ollama offline)"
                
            log.info(f"{agent_name} -> Ollama Fallback")
            try:
                response = self.ollama_client.chat.completions.create(
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=150,
                    response_format={"type": "json_object"} if expect_json else None
                )
                raw_text = response.choices[0].message.content
                source = "Ollama"
            except Exception as e:
                log.error(f"Ollama Fallback failed: {e}")
                return None, f"All LLMs failed."

        return raw_text, source

# Singleton router instance
llm_router = LLMRouter()
