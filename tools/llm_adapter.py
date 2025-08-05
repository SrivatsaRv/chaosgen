"""
Flexible LLM Adapter for ChaosGen

Supports multiple LLM providers (OpenAI, Gemini) with easy configuration
via environment variables or .env file.
"""

import os
import json
from typing import Dict, List, Any, Optional
import structlog
from pathlib import Path

logger = structlog.get_logger()


class LLMAdapter:
    """Flexible adapter for different LLM providers"""

    def __init__(self):
        # Load environment variables from .env file if it exists
        self._load_env_file()

        self.provider = self._detect_provider()
        self.client = self._initialize_client()
        self.model = self._get_model()

        # Print clear status to user
        if self.provider == "mock":
            print("🔧 Using mock mode (no API calls)")
        elif self.provider == "openai":
            print(f"🤖 Using OpenAI ({self.model})")
        elif self.provider == "gemini":
            print(f"🤖 Using Google Gemini ({self.model})")

        logger.info("LLM adapter initialized", provider=self.provider, model=self.model)

    def _load_env_file(self):
        """Load environment variables from .env file if it exists"""
        try:
            from dotenv import load_dotenv

            # Look for .env file in current directory and parent directories
            current_dir = Path.cwd()
            env_file = None

            # Check current directory and up to 3 parent directories
            for i in range(4):
                check_path = current_dir / ".env"
                if check_path.exists():
                    env_file = check_path
                    break
                current_dir = current_dir.parent

            if env_file:
                load_dotenv(env_file)
                logger.info(
                    "Loaded environment variables from .env file", path=str(env_file)
                )
            else:
                logger.info("No .env file found, using system environment variables")

        except ImportError:
            logger.warning("python-dotenv not installed, .env file loading disabled")
            logger.warning("Install with: pip install python-dotenv")
        except Exception as e:
            logger.error("Failed to load .env file", error=str(e))

    def detect_environment(self) -> Dict[str, Any]:
        """Detect and report current environment configuration"""

        # Check library availability
        openai_library_available = False
        gemini_library_available = False

        try:
            from openai import OpenAI

            openai_library_available = True
        except ImportError:
            pass

        try:
            import google.generativeai

            gemini_library_available = True
        except ImportError:
            pass

        env_info = {
            "provider_override": os.getenv("CHAOSGEN_LLM_PROVIDER"),
            "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
            "gemini_key_set": bool(os.getenv("GOOGLE_API_KEY")),
            "mock_mode_set": os.getenv("CHAOSGEN_MOCK_MODE", "false").lower() == "true",
            "openai_model": os.getenv("CHAOSGEN_LLM_MODEL", "gpt-3.5-turbo"),
            "gemini_model": os.getenv("CHAOSGEN_LLM_MODEL", "gemini-1.5-flash"),
            "openai_library_available": openai_library_available,
            "gemini_library_available": gemini_library_available,
            "detected_provider": self.provider,
            "selected_model": self.model,
            "fallback_reason": None,
            "current_model": self.model,  # This is the actual model being used
        }

        # Determine fallback reason
        if env_info["mock_mode_set"]:
            env_info["fallback_reason"] = "Mock mode explicitly enabled"
        elif env_info["provider_override"]:
            if env_info["provider_override"] == "gemini":
                if not env_info["gemini_key_set"]:
                    env_info["fallback_reason"] = (
                        "Gemini forced but GOOGLE_API_KEY not set"
                    )
                elif not env_info["gemini_library_available"]:
                    env_info["fallback_reason"] = (
                        "Gemini forced but google-generativeai library not installed"
                    )
            elif env_info["provider_override"] == "openai":
                if not env_info["openai_key_set"]:
                    env_info["fallback_reason"] = (
                        "OpenAI forced but OPENAI_API_KEY not set"
                    )
                elif not env_info["openai_library_available"]:
                    env_info["fallback_reason"] = (
                        "OpenAI forced but openai library not installed"
                    )
        elif not env_info["openai_key_set"] and not env_info["gemini_key_set"]:
            env_info["fallback_reason"] = "No API keys found"
        elif env_info["gemini_key_set"] and not env_info["gemini_library_available"]:
            env_info["fallback_reason"] = (
                "Google API key found but google-generativeai library not installed"
            )
        elif env_info["openai_key_set"] and not env_info["openai_library_available"]:
            env_info["fallback_reason"] = (
                "OpenAI API key found but openai library not installed"
            )

        return env_info

    def _detect_provider(self) -> str:
        """Detect which LLM provider to use based on environment variables"""

        # Check for provider override
        provider = os.getenv("CHAOSGEN_LLM_PROVIDER", "").lower()

        # If provider is forced, validate the key exists and library is available
        if provider == "gemini":
            if os.getenv("GOOGLE_API_KEY"):
                # Check if library is available
                try:
                    import google.generativeai

                    logger.info("Using Gemini (forced)")
                    return "gemini"
                except ImportError:
                    logger.error(
                        "CHAOSGEN_LLM_PROVIDER=gemini but google-generativeai library not installed"
                    )
                    logger.error("Please install: pip install google-generativeai")
                    return "mock"
            else:
                logger.error("CHAOSGEN_LLM_PROVIDER=gemini but GOOGLE_API_KEY not set")
                logger.error(
                    "Please set GOOGLE_API_KEY or remove CHAOSGEN_LLM_PROVIDER=gemini"
                )
                return "mock"

        if provider == "openai":
            if os.getenv("OPENAI_API_KEY"):
                # Check if library is available
                try:
                    from openai import OpenAI

                    logger.info("Using OpenAI (forced)")
                    return "openai"
                except ImportError:
                    logger.error(
                        "CHAOSGEN_LLM_PROVIDER=openai but openai library not installed"
                    )
                    logger.error("Please install: pip install openai")
                    return "mock"
            else:
                logger.error("CHAOSGEN_LLM_PROVIDER=openai but OPENAI_API_KEY not set")
                logger.error(
                    "Please set OPENAI_API_KEY or remove CHAOSGEN_LLM_PROVIDER=openai"
                )
                return "mock"

        # Auto-detect based on available keys and libraries (only if no provider forced)
        if os.getenv("GOOGLE_API_KEY"):
            try:
                import google.generativeai

                logger.info("Auto-detected Google API key, using Gemini")
                return "gemini"
            except ImportError:
                logger.warning(
                    "Google API key found but google-generativeai library not installed"
                )
                logger.warning(
                    "Falling back to mock mode. Install: pip install google-generativeai"
                )
                return "mock"
        elif os.getenv("OPENAI_API_KEY"):
            try:
                from openai import OpenAI

                logger.info("Auto-detected OpenAI API key, using OpenAI")
                return "openai"
            except ImportError:
                logger.warning("OpenAI API key found but openai library not installed")
                logger.warning("Falling back to mock mode. Install: pip install openai")
                return "mock"
        else:
            logger.info("No API keys found, using mock mode")
            return "mock"

    def _initialize_client(self):
        """Initialize the appropriate LLM client"""

        if self.provider == "openai":
            try:
                from openai import OpenAI

                return OpenAI()
            except ImportError:
                logger.error("OpenAI library not installed. Run: pip install openai")
                return None

        elif self.provider == "gemini":
            try:
                import google.generativeai as genai

                api_key = os.getenv("GOOGLE_API_KEY")
                genai.configure(api_key=api_key)
                return genai
            except ImportError:
                logger.error(
                    "Google Generative AI library not installed. Run: pip install google-generativeai"
                )
                return None

        elif self.provider == "mock":
            return None

        else:
            logger.error(f"Unknown provider: {self.provider}")
            return None

    def _get_model(self) -> str:
        """Get the model to use based on provider and environment variables"""

        if self.provider == "openai":
            return os.getenv("CHAOSGEN_LLM_MODEL", "gpt-3.5-turbo")

        elif self.provider == "gemini":
            return os.getenv("CHAOSGEN_LLM_MODEL", "gemini-1.5-flash")

        elif self.provider == "mock":
            return "mock-model"

        return "unknown"

    def generate_response(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """Generate response from the configured LLM provider"""

        if self.provider == "mock":
            return self._generate_mock_response(prompt)

        try:
            if self.provider == "openai":
                return self._call_openai(prompt, system_prompt, temperature, max_tokens)

            elif self.provider == "gemini":
                return self._call_gemini(prompt, system_prompt, temperature, max_tokens)

            else:
                raise ValueError(f"Unsupported provider: {self.provider}")

        except Exception as e:
            logger.error(f"LLM call failed for provider {self.provider}", error=str(e))
            # Fallback to mock response
            logger.info("Falling back to mock response")
            return self._generate_mock_response(prompt)

    def _call_openai(
        self, prompt: str, system_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        """Call OpenAI API"""

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content.strip()

    def _call_gemini(
        self, prompt: str, system_prompt: str, temperature: float, max_tokens: int
    ) -> str:
        """Call Gemini API"""

        # Combine system prompt and user prompt for Gemini
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        model = self.client.GenerativeModel(self.model)

        # Configure generation parameters
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        response = model.generate_content(
            full_prompt, generation_config=generation_config
        )

        return response.text.strip()

    def _generate_mock_response(self, prompt: str) -> str:
        """Generate a mock response for testing"""

        # Return mock LitmusChaos YAML experiments
        mock_yaml = """apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: frontend-pod-delete
  namespace: demo
spec:
  appinfo:
    appns: demo
    applabel: "app=frontend"
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-delete
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "30"
        - name: CHAOS_INTERVAL
          value: "10"
        - name: FORCE
          value: "false"
---
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: api-cpu-stress
  namespace: demo
spec:
  appinfo:
    appns: demo
    applabel: "app=api"
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-cpu-hog
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "60"
        - name: CPU_CORES
          value: "1"
---
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: database-memory-stress
  namespace: demo
spec:
  appinfo:
    appns: demo
    applabel: "app=database"
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-memory-hog
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "45"
        - name: MEMORY_CONSUMPTION
          value: "200"
"""

        return mock_yaml

    def check_availability(self) -> Dict[str, Any]:
        """Check if the configured provider is available and working"""

        result = {
            "provider": self.provider,
            "model": self.model,
            "available": False,
            "error": None,
            "message": None,
        }

        try:
            if self.provider == "mock":
                result["available"] = True
                result["message"] = "Mock mode - no API calls needed"
                return result

            # Test with a simple prompt
            test_response = self.generate_response("Hello", max_tokens=10)

            if test_response and test_response.strip():
                result["available"] = True
                result["message"] = f"{self.provider} is working correctly"
            else:
                result["available"] = False
                result["error"] = "Empty response received"

        except Exception as e:
            result["available"] = False
            result["error"] = str(e)

        return result


# Global instance for easy access
_llm_adapter = None


def get_llm_adapter() -> LLMAdapter:
    """Get the global LLM adapter instance"""
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = LLMAdapter()
    return _llm_adapter
