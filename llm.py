from pathlib import Path
from PIL import Image
import base64
import io
import json
import os
import re
import requests
import sys

OUTPUT_DIR = Path("/Users/kaartiktejwani/UCLA Files/Playground Code/UI-DETR-1/test_outputs")
DEFAULT_ANNOTATED_IMAGE_FILE = OUTPUT_DIR / "annotated_image.png"
DEFAULT_ELEMENT_IDS_FILE = OUTPUT_DIR / "element_ids.json"
CHAT_LOG_FILE = OUTPUT_DIR / "llm_chat_log.json"
SEMANTICS_FILE = OUTPUT_DIR / "llm_semantics.json"
LLMS_FILE = OUTPUT_DIR / "llms.json"
ENV_FILE = Path("/Users/kaartiktejwani/UCLA Files/Playground Code/UI-DETR-1/.env")


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
        if key and key not in os.environ:
            os.environ[key] = value


def image_to_png_bytes(image_path: Path) -> bytes:
    with Image.open(image_path) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def gemini_api_url(model_name: str) -> str:
    api_version = os.getenv("GEMINI_API_VERSION", "v1alpha")
    return (
        f"https://generativelanguage.googleapis.com/{api_version}/models/"
        f"{model_name}:generateContent"
    )


def supports_thinking_level(model_name: str) -> bool:
    no_thinking_level_models = {
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-001",
    }
    return model_name not in no_thinking_level_models


def extract_gemini_text(response_json: dict) -> str:
    parts = (
        response_json.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text_parts = [part.get("text", "") for part in parts if part.get("text")]
    return "\n".join(text_parts).strip()


def response_schema(element_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            element_id: {
                "type": "string",
                "description": f"Short semantic meaning for UI element {element_id}.",
            }
            for element_id in element_ids
        },
        "required": element_ids,
        "propertyOrdering": element_ids,
    }


def system_prompt() -> str:
    return (
        "You are a UI semantics labeling assistant. You will receive one annotated "
        "screenshot and a checklist of expected element ids. Green boxes identify UI "
        "elements. Each green label is an element id such as E0, E1, E2. Use the "
        "checklist to make sure no ids are skipped. Return only valid JSON. Do not "
        "include markdown, explanations, arrays, coordinates, or a state field."
    )


def sort_element_ids(element_ids: list[str]) -> list[str]:
    return sorted(element_ids, key=lambda element_id: int(element_id[1:]))


def load_element_ids(element_ids_file: Path) -> list[str]:
    data = json.loads(element_ids_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected {element_ids_file} to contain a JSON list.")

    element_ids = []
    for item in data:
        element_id = str(item)
        if re.fullmatch(r"E\d+", element_id):
            element_ids.append(element_id)

    deduped = list(dict.fromkeys(element_ids))
    if not deduped:
        raise ValueError(f"No element ids found in {element_ids_file}.")
    return sort_element_ids(deduped)


def user_prompt(element_ids: list[str]) -> str:
    element_ids_json = json.dumps(element_ids)
    return (
        "Label every boxed UI element in this screenshot with what it does if clicked "
        "or used.\n\n"
        f"Element id checklist, complete and ordered:\n{element_ids_json}\n\n"
        "Return exactly one JSON object in this shape:\n"
        '{"E0":"semantic meaning","E1":"semantic meaning"}\n\n'
        "Requirements:\n"
        "- Use exactly the element ids from the checklist as keys. No missing keys. No extra keys.\n"
        "- Order keys by element id ascending, exactly matching the checklist order.\n"
        "- Be specific enough that a human knows what clicking the element would do.\n"
        "- Inspect each box in the screenshot independently. Do not assume adjacent "
        "element ids are the same type of UI.\n"
        "- Do not write generic labels like app icon or system utility when a specific "
        "meaning is visible. Name the app or utility, for example Chrome icon, Finder "
        "icon, microphone mute button, camera toggle, meeting hang up button, screen "
        "share button, captions button, participants button, chat button, more options "
        "button, address bar, bookmark, tab, or extension button.\n"
        "- If an element is hard to read, keep its key and use the best visible "
        "interpretation. If there is no useful visual context, write unknown element.\n"
        "- Values must be short strings, not nested objects."
    )


def parse_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object mapping element ids to semantic strings.")

    cleaned = {}
    for key, value in parsed.items():
        if not re.fullmatch(r"E\d+", str(key)):
            continue
        cleaned[str(key)] = str(value)

    return dict(sorted(cleaned.items(), key=lambda item: int(item[0][1:])))


def parse_complete_string_pairs(content: str) -> dict:
    pairs = {}
    pattern = re.compile(r'"(E\d+)"\s*:\s*"((?:\\.|[^"\\])*)"')
    for match in pattern.finditer(content):
        key = match.group(1)
        raw_value = match.group(2)
        try:
            value = json.loads(f'"{raw_value}"')
        except json.JSONDecodeError:
            value = raw_value
        pairs[key] = value
    return dict(sorted(pairs.items(), key=lambda item: int(item[0][1:])))


def normalize_semantics(parsed: dict, element_ids: list[str]) -> dict:
    normalized = {}
    for element_id in element_ids:
        value = parsed.get(element_id, "unknown element")
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        normalized[element_id] = value
    return normalized


def main() -> None:
    load_dotenv(ENV_FILE)

    annotated_image_file = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_ANNOTATED_IMAGE_FILE
    element_ids_file = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else DEFAULT_ELEMENT_IDS_FILE

    if not annotated_image_file.exists():
        raise FileNotFoundError(f"Annotated image file not found: {annotated_image_file}")
    if not element_ids_file.exists():
        raise FileNotFoundError(f"Element ids file not found: {element_ids_file}")

    element_ids = load_element_ids(element_ids_file)
    image_bytes = image_to_png_bytes(annotated_image_file)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    prompt = user_prompt(element_ids)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("Set GEMINI_API_KEY before running llm.py.")

    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt()}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
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
            "responseSchema": response_schema(element_ids),
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "12000")),
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
    response_json = response.json()
    content = extract_gemini_text(response_json)

    chat_log = {
        "model": model_name,
        "provider": "gemini",
        "orchestrator": "rest",
        "api_version": os.getenv("GEMINI_API_VERSION", "v1alpha"),
        "annotated_image_file": str(annotated_image_file),
        "element_ids_file": str(element_ids_file),
        "element_ids": element_ids,
        "messages": [
            {"role": "system", "content": system_prompt()},
            {
                "role": "user",
                "content": prompt,
                "image_base64_png": image_b64,
            },
            {
                "role": "assistant",
                "content": content,
                "thinking": "Gemini API does not expose hidden reasoning text.",
                "usage_metadata": response_json.get("usageMetadata", {}),
                "candidates": response_json.get("candidates", []),
            },
        ],
        "raw_response": response_json,
    }

    try:
        parsed = parse_json_object(content)
        semantics = normalize_semantics(parsed, element_ids)
    except (json.JSONDecodeError, ValueError) as exc:
        partial = parse_complete_string_pairs(content)
        semantics = normalize_semantics(partial, element_ids)
        if not partial:
            semantics = {
                "_error": str(exc),
                "_raw_content": content,
            }

    OUTPUT_DIR.mkdir(exist_ok=True)
    CHAT_LOG_FILE.write_text(json.dumps(chat_log, indent=2), encoding="utf-8")
    SEMANTICS_FILE.write_text(json.dumps(semantics, indent=2), encoding="utf-8")
    LLMS_FILE.write_text(json.dumps(semantics, indent=2), encoding="utf-8")

    print(f"Saved LLM outputs to {OUTPUT_DIR}")
    # print("\n=== LLM conversation ===")
    # print(f"model: {model_name}")
    # print(f"system: {system_prompt()}")
    # print(f"user: {prompt}")
    # print(f"image: {annotated_image_file}")
    # print(f"element_ids: {element_ids_file}")
    # print(f"assistant: {content}")
    # print("thinking: Gemini API does not expose hidden reasoning text.")
    # print(f"metadata: {json.dumps(response_json.get('usageMetadata', {}), indent=2)}")


if __name__ == "__main__":
    main()
