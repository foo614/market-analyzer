import os
import unittest

import trading_system.llm_router as router_module


class FakeChoice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        return FakeResponse('{"sentiment":"Neutral","reason":"ok"}')


class FakeChat:
    def __init__(self, owner):
        self.completions = FakeCompletions(owner)


class FakeOpenAIClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.chat = FakeChat(self)
        FakeOpenAIClient.instances.append(self)


class LLMRouterOpenRouterTest(unittest.TestCase):
    def setUp(self):
        self.original_openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        self.original_openrouter_model = os.environ.get("OPENROUTER_MODEL")
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
        os.environ.pop("OPENROUTER_MODEL", None)

        self.original_openai = router_module.OpenAI
        self.original_genai = router_module.genai
        self.original_check_ollama = router_module.check_ollama_health
        self.original_get_gemini_keys = router_module.get_gemini_api_keys
        self.original_get_credential = router_module.get_credential

        FakeOpenAIClient.instances = []
        router_module.OpenAI = FakeOpenAIClient
        router_module.genai = None
        router_module.check_ollama_health = lambda: (False, "offline")
        router_module.get_gemini_api_keys = lambda: []
        router_module.get_credential = lambda key, env_var=None: os.environ.get(env_var) if env_var else None

    def tearDown(self):
        if self.original_openrouter_key is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = self.original_openrouter_key

        if self.original_openrouter_model is None:
            os.environ.pop("OPENROUTER_MODEL", None)
        else:
            os.environ["OPENROUTER_MODEL"] = self.original_openrouter_model

        router_module.OpenAI = self.original_openai
        router_module.genai = self.original_genai
        router_module.check_ollama_health = self.original_check_ollama
        router_module.get_gemini_api_keys = self.original_get_gemini_keys
        router_module.get_credential = self.original_get_credential

    def test_openrouter_client_is_used_before_other_fallbacks(self):
        router = router_module.LLMRouter()

        raw, source = router.route_request("classify", expect_json=True, agent_name="Test")

        self.assertEqual(source, "OpenRouter")
        self.assertIn("Neutral", raw)
        openrouter = router.openrouter_client
        self.assertEqual(openrouter.kwargs["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(openrouter.kwargs["api_key"], "test-openrouter-key")
        self.assertEqual(openrouter.calls[0]["model"], "openai/gpt-4o-mini")
        self.assertEqual(openrouter.calls[0]["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
