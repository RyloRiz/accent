from pathlib import Path
from PIL import Image
import base64
import io
import json
import os
import re
import requests
import time

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "test_outputs"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = PROJECT_DIR / OUTPUT_DIR

ENV_FILE = Path(os.getenv("PIPELINE_ENV_FILE", str(PROJECT_DIR / ".env")))
LLMS_FILE = OUTPUT_DIR / "llms.json"
ANNOTATED_IMAGE_FILE = OUTPUT_DIR / "annotated_image.png"
CONFLICT_RESOLUTION_FILE = OUTPUT_DIR / "conflict_resolution.json"
INTENT_RAW_RESPONSE_FILE = OUTPUT_DIR / "intent_raw_response.json"


def load_dotenv(env_file: Path) -> None:
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ[key] = value


def image_to_base64_png(image_path: Path) -> str:
    with Image.open(image_path) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def gemini_api_url(model_name: str) -> str:
    api_version = os.getenv("GEMINI_API_VERSION", "v1alpha")
    return (
        f"https://generativelanguage.googleapis.com/{api_version}/models/"
        f"{model_name}:generateContent"
    )


def provider_name() -> str:
    return (
        os.getenv("INTENT_PROVIDER")
        or os.getenv("LLM_PROVIDER", "gemini")
    ).strip().lower()


def ollama_api_url() -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    return f"{base_url}/api/chat"


def ollama_model_name() -> str:
    return os.getenv("OLLAMA_INTENT_MODEL") or os.getenv("OLLAMA_MODEL", "gemma4:e4b")


def supports_thinking_level(model_name: str) -> bool:
    return model_name not in {
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-001",
    }


def model_candidates() -> list[str]:
    models = [
        os.getenv("GEMINI_INTENT_MODEL")
        or os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    ]
    fallback = (
        os.getenv("GEMINI_INTENT_FALLBACK_MODEL")
        or os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-pro-preview")
    )
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def post_gemini_with_retries(payload: dict, api_key: str, model_name: str) -> requests.Response:
    attempts = int(os.getenv("GEMINI_INTENT_RETRIES", os.getenv("GEMINI_RETRIES", "3")))
    base_delay = float(os.getenv("GEMINI_RETRY_BASE_SECONDS", "2"))
    retry_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, attempts + 1):
        response = requests.post(
            gemini_api_url(model_name),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=payload,
            timeout=int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120")),
        )
        if response.status_code not in retry_statuses:
            return response
        if attempt == attempts:
            return response

        delay = base_delay * attempt
        print(
            f"Gemini intent model {model_name} returned {response.status_code}; "
            f"retrying in {delay:.1f}s..."
        )
        time.sleep(delay)

    return response


def post_ollama_chat(system: str, prompt: str, model_name: str) -> dict:
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0")),
            "num_predict": int(os.getenv("OLLAMA_INTENT_NUM_PREDICT", "2000")),
        },
    }
    response = requests.post(
        ollama_api_url(),
        json=payload,
        timeout=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240")),
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Ollama intent request failed for model {model_name}: "
            f"{response.status_code} {response.text}"
        ) from exc
    return response.json()


def extract_gemini_text(response_json: dict) -> str:
    parts = (
        response_json.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()


def extract_ollama_text(response_json: dict) -> str:
    return (
        response_json.get("message", {}).get("content")
        or response_json.get("response")
        or ""
    ).strip()


def parse_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def keyword_fallback_resolution(user_intent: str, semantics: dict, raw_content: str = "") -> dict:
    intent = user_intent.lower()
    scored = []
    intent_words = set(re.findall(r"[a-zA-Z0-9]+", intent))

    preferred_terms = []
    if any(word in intent for word in ["hear", "mic", "microphone", "mute", "unmute", "sun", "suna"]):
        preferred_terms.extend(["microphone", "mic", "mute", "unmute"])
    if any(word in intent for word in ["camera", "video"]):
        preferred_terms.extend(["camera", "video"])
    if any(word in intent for word in ["close", "quit", "exit", "band"]):
        preferred_terms.extend(["close", "quit", "exit"])
    if any(word in intent for word in ["desktop", "home"]):
        preferred_terms.extend(["desktop", "home", "finder", "dock"])
    if any(word in intent for word in ["login", "log in", "sign in"]):
        preferred_terms.extend(["login", "log in", "sign in", "sign-in"])

    for element_id, semantic in semantics.items():
        semantic_lower = semantic.lower()
        score = 0
        score += sum(4 for term in preferred_terms if term in semantic_lower)
        semantic_words = set(re.findall(r"[a-zA-Z0-9]+", semantic_lower))
        score += len(intent_words & semantic_words)
        if any(bad in semantic_lower for bad in ["label", "decorative", "unknown"]):
            score -= 2
        if score > 0:
            scored.append((score, element_id, semantic))

    if scored:
        scored.sort(key=lambda item: (-item[0], int(item[1][1:])))
        _, selected, selected_semantic = scored[0]
        return {
            "plaintext_response": (
                "The local model did not return valid JSON, so I matched the request "
                f"to the closest visible control: {selected}."
            ),
            "selected_element_id": selected,
            "selected_semantic": selected_semantic,
            "direction_for_user": f"Click {selected_semantic}.",
        }

    return {
        "plaintext_response": (
            "The local model did not return valid JSON and no matching control was found."
        ),
        "selected_element_id": "NONE",
        "selected_semantic": "",
        "direction_for_user": "I could not find a matching button.",
    }


def load_semantics(llms_file: Path) -> dict:
    data = json.loads(llms_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected {llms_file} to contain a JSON object.")
    return {
        str(key): str(value)
        for key, value in data.items()
        if re.fullmatch(r"E\d+", str(key))
    }


def user_intent_from_env() -> str:
    value = (
        os.getenv("USER_INTENT")
        or os.getenv("USER_INPUT")
        or os.getenv("USER_QUERY")
        or ""
    ).strip()
    if not value:
        raise EnvironmentError("Set USER_INTENT in .env, for example USER_INTENT=Why cant they hear me?")
    return value


def response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "plaintext_response": {"type": "string"},
            "selected_element_id": {"type": "string"},
            "selected_semantic": {"type": "string"},
            "direction_for_user": {"type": "string"},
        },
        "required": [
            "plaintext_response",
            "selected_element_id",
            "selected_semantic",
            "direction_for_user",
        ],
        "propertyOrdering": [
            "plaintext_response",
            "selected_element_id",
            "selected_semantic",
            "direction_for_user",
        ],
    }


def system_prompt() -> str:
    return (
        "You are an intent resolver for a UI automation assistant. You receive a user's "
        "natural-language sentence, a JSON map of UI element ids to semantic descriptions, "
        "and an annotated screenshot. Infer what the user wants to do, explain why, and "
        "choose exactly one element id to highlight. Return only valid JSON. Never return "
        "an empty response. Never include markdown or prose outside the JSON object."
    )


def user_prompt(user_intent: str, semantics: dict) -> str:
    return (
        f"User sentence:\n{user_intent}\n\n"
        "Available UI elements, mapping element id to semantic description:\n"
        f"{json.dumps(semantics, indent=2)}\n\n"
        "Resolve the user's intent. The plaintext_response must be plain English with "
        "three short parts: WHAT the user is probably trying to do, WHY that action follows "
        "from their sentence, and ACTION naming the selected element id. Then choose the "
        "single best UI element to click/touch/highlight.\n\n"
        "Rules:\n"
        "- Return exactly one JSON object with keys plaintext_response, selected_element_id, "
        "selected_semantic, and direction_for_user.\n"
        "- Do not leave direction_for_user empty.\n"
        "- selected_element_id must be one of the provided E# ids, or NONE if no element fits.\n"
        "- Prefer direct action controls over labels, app icons, decorative images, or text.\n"
        "- For video-call audio problems like 'Why can't they hear me?', infer that other "
        "people cannot hear the user and prefer the microphone/unmute control.\n"
        "- Use the screenshot only as context when the semantic descriptions are ambiguous.\n"
        "- Be concise but explicit. The plaintext_response should be plain English.\n"
        "- direction_for_user must be one short sentence shown above the selected button. "
        "Write direction_for_user in the same human language as the user's sentence "
        "(Spanish, Hindi, English, etc.). Keep the action clear and natural in that language."
    )


def bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_resolution(parsed: dict, semantics: dict, user_intent: str) -> dict:
    selected = str(parsed.get("selected_element_id", "NONE"))
    if selected not in semantics:
        selected = "NONE"

    selected_semantic = semantics.get(selected, "")
    if selected == "NONE":
        selected_semantic = ""
    direction_for_user = str(parsed.get("direction_for_user", "")).strip()
    if not direction_for_user:
        if selected != "NONE" and selected_semantic:
            direction_for_user = f"Click {selected_semantic}."
        else:
            direction_for_user = "I could not find a matching button."

    return {
        "user_intent": user_intent,
        "plaintext_response": str(parsed.get("plaintext_response", "")).strip(),
        "selected_element_id": selected,
        "selected_semantic": selected_semantic,
        "direction_for_user": direction_for_user,
    }


def main() -> None:
    start = time.perf_counter()
    load_dotenv(ENV_FILE)

    if not LLMS_FILE.exists():
        raise FileNotFoundError(f"LLM semantics file not found: {LLMS_FILE}")
    include_image = bool_env("INCLUDE_INTENT_IMAGE", False)
    if include_image and not ANNOTATED_IMAGE_FILE.exists():
        raise FileNotFoundError(f"Annotated image file not found: {ANNOTATED_IMAGE_FILE}")

    semantics = load_semantics(LLMS_FILE)
    if not semantics:
        raise ValueError(f"No E# semantic entries found in {LLMS_FILE}")

    user_intent = user_intent_from_env()
    provider = provider_name()
    api_key = os.getenv("GEMINI_API_KEY")
    if provider == "gemini" and not api_key:
        raise EnvironmentError("Set GEMINI_API_KEY before running resolve_intent.py.")

    user_parts = [{"text": user_prompt(user_intent, semantics)}]
    if include_image:
        image_b64 = image_to_base64_png(ANNOTATED_IMAGE_FILE)
        user_parts.append({
            "inlineData": {
                "mimeType": "image/png",
                "data": image_b64,
            }
        })

    base_payload = {
        "systemInstruction": {"parts": [{"text": system_prompt()}]},
        "contents": [
            {
                "role": "user",
                "parts": user_parts,
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema(),
            "maxOutputTokens": int(os.getenv("GEMINI_INTENT_MAX_OUTPUT_TOKENS", "2000")),
        },
    }

    raw_response_json = {}
    if provider == "ollama":
        used_model = ollama_model_name()
        response_json = post_ollama_chat(
            system_prompt(),
            user_prompt(user_intent, semantics),
            used_model,
        )
        raw_response_json = response_json
        content = extract_ollama_text(response_json)
    else:
        response = None
        used_model = None
        last_error = None
        candidates = model_candidates()
        for model_name in candidates:
            payload = json.loads(json.dumps(base_payload))
            if supports_thinking_level(model_name):
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": os.getenv("GEMINI_THINKING_LEVEL", "low"),
                }

            response = post_gemini_with_retries(payload, api_key, model_name)
            if response.ok:
                used_model = model_name
                break

            last_error = (
                f"Gemini API request failed for model {model_name}: "
                f"{response.status_code} {response.text}"
            )
            if model_name != candidates[-1]:
                print(f"{last_error}\nTrying fallback intent model...")

        if response is None or not response.ok:
            raise RuntimeError(last_error or "Gemini API request failed for intent resolver.")

        raw_response_json = response.json()
        content = extract_gemini_text(raw_response_json)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INTENT_RAW_RESPONSE_FILE.write_text(
        json.dumps({
            "provider": provider,
            "model": used_model,
            "content": content,
            "raw_response": raw_response_json,
        }, indent=2),
        encoding="utf-8",
    )

    try:
        parsed = parse_json_object(content)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Intent model returned invalid JSON; using fallback matcher: {exc}")
        parsed = keyword_fallback_resolution(user_intent, semantics, content)
    required_keys = {"plaintext_response", "selected_element_id", "selected_semantic", "direction_for_user"}
    if not required_keys.issubset(parsed.keys()) or str(parsed.get("selected_element_id", "NONE")) not in semantics:
        parsed = keyword_fallback_resolution(user_intent, semantics, content)
    resolution = normalize_resolution(parsed, semantics, user_intent)

    CONFLICT_RESOLUTION_FILE.write_text(json.dumps(resolution, indent=2), encoding="utf-8")
    print(f"Saved intent resolution to {CONFLICT_RESOLUTION_FILE}")
    print(f"Intent model: {used_model}")
    print(f"Resolved user intent: {user_intent}")
    print(resolution["plaintext_response"])
    print(f"Intent resolution finished in {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
