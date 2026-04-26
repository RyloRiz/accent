from pathlib import Path
from PIL import Image
import base64
import io
import json
import os
import re
import requests

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "test_outputs"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = PROJECT_DIR / OUTPUT_DIR

ENV_FILE = Path(os.getenv("PIPELINE_ENV_FILE", str(PROJECT_DIR / ".env")))
LLMS_FILE = OUTPUT_DIR / "llms.json"
ANNOTATED_IMAGE_FILE = OUTPUT_DIR / "annotated_image.png"
CONFLICT_RESOLUTION_FILE = OUTPUT_DIR / "conflict_resolution.json"


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


def supports_thinking_level(model_name: str) -> bool:
    return model_name not in {
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-001",
    }


def extract_gemini_text(response_json: dict) -> str:
    parts = (
        response_json.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()


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
        "choose exactly one element id to highlight. Return only valid JSON."
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


def normalize_resolution(parsed: dict, semantics: dict, user_intent: str) -> dict:
    selected = str(parsed.get("selected_element_id", "NONE"))
    if selected not in semantics:
        selected = "NONE"

    selected_semantic = semantics.get(selected, "")
    if selected == "NONE":
        selected_semantic = ""

    return {
        "user_intent": user_intent,
        "plaintext_response": str(parsed.get("plaintext_response", "")).strip(),
        "selected_element_id": selected,
        "selected_semantic": selected_semantic,
        "direction_for_user": str(parsed.get("direction_for_user", "")).strip(),
    }


def main() -> None:
    load_dotenv(ENV_FILE)

    if not LLMS_FILE.exists():
        raise FileNotFoundError(f"LLM semantics file not found: {LLMS_FILE}")
    if not ANNOTATED_IMAGE_FILE.exists():
        raise FileNotFoundError(f"Annotated image file not found: {ANNOTATED_IMAGE_FILE}")

    semantics = load_semantics(LLMS_FILE)
    if not semantics:
        raise ValueError(f"No E# semantic entries found in {LLMS_FILE}")

    user_intent = user_intent_from_env()
    image_b64 = image_to_base64_png(ANNOTATED_IMAGE_FILE)
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("Set GEMINI_API_KEY before running intent_resolver.py.")

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt()}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_prompt(user_intent, semantics)},
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": image_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema(),
            "maxOutputTokens": int(os.getenv("GEMINI_INTENT_MAX_OUTPUT_TOKENS", "2000")),
        },
    }
    if supports_thinking_level(model_name):
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingLevel": os.getenv("GEMINI_THINKING_LEVEL", "low"),
        }

    response = requests.post(
        gemini_api_url(model_name),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        json=payload,
        timeout=int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120")),
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Gemini API request failed for model {model_name}: "
            f"{response.status_code} {response.text}"
        ) from exc

    content = extract_gemini_text(response.json())
    parsed = parse_json_object(content)
    resolution = normalize_resolution(parsed, semantics, user_intent)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CONFLICT_RESOLUTION_FILE.write_text(json.dumps(resolution, indent=2), encoding="utf-8")
    print(f"Saved intent resolution to {CONFLICT_RESOLUTION_FILE}")
    print(f"Resolved user intent: {user_intent}")
    print(resolution["plaintext_response"])


if __name__ == "__main__":
    main()
