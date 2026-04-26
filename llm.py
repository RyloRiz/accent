from pathlib import Path
from PIL import Image
import base64
import io
import json
import os
import re
import requests
import sys
import time

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "test_outputs"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = PROJECT_DIR / OUTPUT_DIR

DEFAULT_ANNOTATED_IMAGE_FILE = OUTPUT_DIR / "annotated_image.png"
DEFAULT_CROP_SHEET_FILES = [OUTPUT_DIR / f"crop_sheet_{index}.png" for index in range(1, 5)]
LEGACY_CROP_SHEET_FILE = OUTPUT_DIR / "crop_sheet.png"
DEFAULT_ELEMENT_IDS_FILE = OUTPUT_DIR / "element_ids.json"
DEFAULT_DETECTIONS_FILE = OUTPUT_DIR / "detections.json"
CHAT_LOG_FILE = OUTPUT_DIR / "llm_chat_log.json"
LLMS_FILE = OUTPUT_DIR / "llms.json"
FINAL_ACTION_BUTTONS_FILE = OUTPUT_DIR / "final_action_buttons.json"
ENV_FILE = Path(os.getenv("PIPELINE_ENV_FILE", str(PROJECT_DIR / ".env")))


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


def image_to_model_image(image_path: Path) -> tuple[str, bytes]:
    image_format = os.getenv("GEMINI_IMAGE_FORMAT", "jpeg").strip().lower()
    with Image.open(image_path) as image:
        buffer = io.BytesIO()
        rgb = image.convert("RGB")
        if image_format == "png":
            rgb.save(buffer, format="PNG")
            return "image/png", buffer.getvalue()
        quality = int(os.getenv("GEMINI_IMAGE_JPEG_QUALITY", "82"))
        rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
        return "image/jpeg", buffer.getvalue()


def gemini_api_url(model_name: str) -> str:
    api_version = os.getenv("GEMINI_API_VERSION", "v1alpha")
    return (
        f"https://generativelanguage.googleapis.com/{api_version}/models/"
        f"{model_name}:generateContent"
    )


def provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower()


def ollama_api_url() -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    return f"{base_url}/api/chat"


def supports_thinking_level(model_name: str) -> bool:
    no_thinking_level_models = {
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-001",
    }
    return model_name not in no_thinking_level_models


def model_candidates() -> list[str]:
    models = [os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")]
    fallback = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-pro-preview")
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def ollama_model_name() -> str:
    return os.getenv("OLLAMA_MODEL", "gemma4:e4b")


def post_gemini_with_retries(
    payload: dict,
    api_key: str,
    model_name: str,
    batch_label: str,
) -> requests.Response:
    attempts = int(os.getenv("GEMINI_RETRIES", "3"))
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
            f"Gemini {model_name} returned {response.status_code} for {batch_label}; "
            f"retrying in {delay:.1f}s..."
        )
        time.sleep(delay)

    return response


def post_ollama_chat(
    *,
    system: str,
    prompt: str,
    image_b64s: list[str],
    model_name: str,
) -> dict:
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": prompt,
                "images": image_b64s,
            },
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0")),
            "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "12000")),
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
            f"Ollama request failed for model {model_name}: "
            f"{response.status_code} {response.text}"
        ) from exc
    return response.json()


def extract_gemini_text(response_json: dict) -> str:
    parts = (
        response_json.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text_parts = [part.get("text", "") for part in parts if part.get("text")]
    return "\n".join(text_parts).strip()


def extract_ollama_text(response_json: dict) -> str:
    return (
        response_json.get("message", {}).get("content")
        or response_json.get("response")
        or ""
    ).strip()


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
        "screenshot, one or more crop-sheet images, and a checklist of expected element "
        "ids. The annotated screenshot gives full-page context. The crop sheets contain "
        "zoomed tiles labeled E0, E1, E2, etc.; those crop tiles are the source of truth "
        "for which id belongs to which exact element. Use the checklist to make sure no "
        "ids are skipped. Return only valid JSON. Do not include markdown, explanations, "
        "arrays, coordinates, or a state field."
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
        "You will receive multiple images:\n"
        "1. Full annotated screenshot for overall screen context.\n"
        "2. Crop sheets with one zoomed tile per element id. Use these crop sheets to "
        "identify the exact icon/control for each id.\n\n"
        "Return exactly one JSON object in this shape:\n"
        '{"E0":"semantic meaning","E1":"semantic meaning"}\n\n'
        "Requirements:\n"
        "- Use exactly the element ids from the checklist as keys. No missing keys. No extra keys.\n"
        "- Order keys by element id ascending, exactly matching the checklist order.\n"
        "- Be specific enough that a human knows what clicking the element would do.\n"
        "- Include useful visual details in the same string: color, shape, icon/text, "
        "screen location, nearby visual context, selected/disabled/emphasized state, "
        "and whether it appears in the menu bar, browser chrome, page content, meeting "
        "controls, or dock.\n"
        "- Use the crop sheets to decide which label belongs to which exact element. "
        "Do not label a neighboring arrow, menu, or grouped control unless that "
        "specific id's crop shows it.\n"
        "- Use the full annotated screenshot only for broader context and location.\n"
        "- Inspect each box in the screenshot independently. Do not assume adjacent "
        "element ids are the same type of UI.\n"
        "- Do not write generic labels like app icon or system utility when a specific "
        "meaning is visible. Name the app or utility, for example Chrome icon, Finder "
        "icon, microphone mute button, camera toggle, meeting hang up button, screen "
        "share button, captions button, participants button, chat button, more options "
        "button, address bar, bookmark, tab, or extension button.\n"
        "- If an element is hard to read, keep its key and use the best visible "
        "interpretation. If there is no useful visual context, write unknown element.\n"
        "- Values must be single strings, not nested objects. Aim for one concise "
        "sentence per element."
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


def load_detections(detections_file: Path) -> list[dict]:
    data = json.loads(detections_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected {detections_file} to contain a JSON list.")
    return [item for item in data if isinstance(item, dict)]


def box_pixels(box: list) -> dict:
    x1, y1, x2, y2 = [round(float(value), 2) for value in box]
    width = round(x2 - x1, 2)
    height = round(y2 - y1, 2)
    return {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": width,
        "height": height,
        "center_x": round(x1 + (width / 2), 2),
        "center_y": round(y1 + (height / 2), 2),
    }


def build_final_action_buttons(detections: list[dict], semantics: dict) -> dict:
    final = {}
    for detection in detections:
        element_id = detection.get("element_id")
        box = detection.get("box")
        if not isinstance(element_id, str) or not isinstance(box, list) or len(box) != 4:
            continue

        final[element_id] = {
            "semantic": semantics.get(element_id, "unknown element"),
            "box": box_pixels(box),
            "box_format": detection.get("box_format", "xyxy"),
            "class": detection.get("class"),
            "confidence": detection.get("confidence"),
        }

    return dict(sorted(final.items(), key=lambda item: int(item[0][1:])))


def default_crop_sheet_files() -> list[Path]:
    files = [path for path in DEFAULT_CROP_SHEET_FILES if path.exists()]
    if files:
        return files
    if LEGACY_CROP_SHEET_FILE.exists():
        return [LEGACY_CROP_SHEET_FILE]
    return DEFAULT_CROP_SHEET_FILES


def element_id_chunks(element_ids: list[str]) -> list[list[str]]:
    chunks = []
    start = 0
    for sheet_index in range(4):
        if start >= len(element_ids):
            break
        end = len(element_ids) if sheet_index == 3 else min(start + 50, len(element_ids))
        chunks.append(element_ids[start:end])
        start = end
    return chunks


def grouped_batches(
    crop_sheet_files: list[Path],
    id_chunks: list[list[str]],
    sheets_per_call: int,
    max_ids_per_call: int,
) -> list[tuple[list[Path], list[str]]]:
    batches = []
    sheets_per_call = max(1, sheets_per_call)
    max_ids_per_call = max(1, max_ids_per_call)

    entries = []
    for crop_sheet_file, ids in zip(crop_sheet_files, id_chunks):
        for start in range(0, len(ids), max_ids_per_call):
            entries.append((crop_sheet_file, ids[start:start + max_ids_per_call]))

    batch_files = []
    batch_ids = []
    for crop_sheet_file, ids in entries:
        next_files = batch_files if crop_sheet_file in batch_files else [*batch_files, crop_sheet_file]
        would_exceed_files = len(next_files) > sheets_per_call
        would_exceed_ids = batch_ids and len(batch_ids) + len(ids) > max_ids_per_call

        if would_exceed_files or would_exceed_ids:
            batches.append((batch_files, batch_ids))
            batch_files = []
            batch_ids = []
            next_files = [crop_sheet_file]

        batch_files = next_files
        batch_ids.extend(ids)

    if batch_ids:
        batches.append((batch_files, batch_ids))

    return batches


def main() -> None:
    load_dotenv(ENV_FILE)

    annotated_image_file = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_ANNOTATED_IMAGE_FILE
    element_ids_file = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else DEFAULT_ELEMENT_IDS_FILE
    crop_sheet_files = [Path(sys.argv[3]).expanduser()] if len(sys.argv) > 3 else default_crop_sheet_files()
    detections_file = Path(sys.argv[4]).expanduser() if len(sys.argv) > 4 else DEFAULT_DETECTIONS_FILE

    if not annotated_image_file.exists():
        raise FileNotFoundError(f"Annotated image file not found: {annotated_image_file}")
    if not element_ids_file.exists():
        raise FileNotFoundError(f"Element ids file not found: {element_ids_file}")
    missing_crop_sheets = [path for path in crop_sheet_files if not path.exists()]
    if missing_crop_sheets:
        raise FileNotFoundError(f"Crop sheet file not found: {missing_crop_sheets[0]}")
    if not detections_file.exists():
        raise FileNotFoundError(f"Detections file not found: {detections_file}")

    element_ids = load_element_ids(element_ids_file)
    detections = load_detections(detections_file)
    annotated_mime_type, annotated_image_bytes = image_to_model_image(annotated_image_file)
    annotated_image_b64 = base64.b64encode(annotated_image_bytes).decode("ascii")
    primary_model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    provider = provider_name()

    api_key = os.getenv("GEMINI_API_KEY")
    if provider == "gemini" and not api_key:
        raise EnvironmentError("Set GEMINI_API_KEY before running llm.py.")

    id_chunks = element_id_chunks(element_ids)
    if len(crop_sheet_files) == 1 and crop_sheet_files[0] == LEGACY_CROP_SHEET_FILE:
        id_chunks = [element_ids]
    if len(crop_sheet_files) < len(id_chunks):
        raise ValueError(
            f"Found {len(crop_sheet_files)} crop sheet(s), but {len(id_chunks)} are needed "
            f"for {len(element_ids)} element ids. Run test.py again."
        )

    sheets_per_call = int(os.getenv("CROP_SHEETS_PER_LLM_CALL", "4"))
    max_ids_per_call = int(os.getenv("MAX_IDS_PER_LLM_CALL", "150"))
    batches = grouped_batches(crop_sheet_files, id_chunks, sheets_per_call, max_ids_per_call)
    semantics = {}
    batch_logs = []
    for batch_index, (batch_crop_sheet_files, batch_ids) in enumerate(batches, 1):
        prompt = user_prompt(batch_ids)
        user_parts = [
            {"text": prompt},
            {"text": "Image 1: full annotated screenshot for context."},
            {
                "inlineData": {
                    "mimeType": annotated_mime_type,
                    "data": annotated_image_b64,
                }
            },
        ]
        for sheet_index, crop_sheet_file in enumerate(batch_crop_sheet_files, 1):
            crop_sheet_mime_type, crop_sheet_bytes = image_to_model_image(crop_sheet_file)
            crop_sheet_b64 = base64.b64encode(crop_sheet_bytes).decode("ascii")
            user_parts.extend([
                {
                    "text": (
                        f"Crop sheet {sheet_index} in this request. Use these labeled "
                        "tiles as the source of truth for only the ids shown in this sheet."
                    )
                },
                {
                    "inlineData": {
                        "mimeType": crop_sheet_mime_type,
                        "data": crop_sheet_b64,
                    }
                },
            ])

        batch_label = f"batch {batch_index}, ids {batch_ids[0]}-{batch_ids[-1]}"

        if provider == "ollama":
            used_model_name = ollama_model_name()
            ollama_prompt = "\n\n".join(
                part["text"] for part in user_parts if "text" in part
            )
            image_b64s = [
                part["inlineData"]["data"]
                for part in user_parts
                if "inlineData" in part
            ]
            response_json = post_ollama_chat(
                system=system_prompt(),
                prompt=ollama_prompt,
                image_b64s=image_b64s,
                model_name=used_model_name,
            )
            content = extract_ollama_text(response_json)
        else:
            response = None
            used_model_name = primary_model_name
            last_error = None
            candidates = model_candidates()

            for candidate_model_name in candidates:
                payload = {
                    "systemInstruction": {
                        "parts": [{"text": system_prompt()}],
                    },
                    "contents": [
                        {
                            "role": "user",
                            "parts": user_parts,
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": response_schema(batch_ids),
                        "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "12000")),
                    },
                }
                if supports_thinking_level(candidate_model_name):
                    payload["generationConfig"]["thinkingConfig"] = {
                        "thinkingLevel": os.getenv("GEMINI_THINKING_LEVEL", "low"),
                    }

                response = post_gemini_with_retries(payload, api_key, candidate_model_name, batch_label)
                if response.ok:
                    used_model_name = candidate_model_name
                    break

                last_error = (
                    f"Gemini API request failed for model {candidate_model_name}, "
                    f"{batch_label}: {response.status_code} {response.text}"
                )
                if candidate_model_name != candidates[-1]:
                    print(f"{last_error}\nTrying fallback model...")

            if response is None or not response.ok:
                raise RuntimeError(last_error or f"Gemini API request failed for {batch_label}")

            response_json = response.json()
            content = extract_gemini_text(response_json)

        try:
            parsed = parse_json_object(content)
            batch_semantics = normalize_semantics(parsed, batch_ids)
        except (json.JSONDecodeError, ValueError):
            partial = parse_complete_string_pairs(content)
            batch_semantics = normalize_semantics(partial, batch_ids)

        semantics.update(batch_semantics)
        batch_logs.append({
            "batch_index": batch_index,
            "model": used_model_name,
            "crop_sheet_files": [str(path) for path in batch_crop_sheet_files],
            "element_ids": batch_ids,
            "content": content,
            "usage_metadata": response_json.get("usageMetadata", response_json.get("eval_count", {})),
            "candidates": response_json.get("candidates", []),
            "raw_response": response_json,
        })

    semantics = normalize_semantics(semantics, element_ids)

    chat_log = {
        "model": ollama_model_name() if provider == "ollama" else primary_model_name,
        "model_candidates": model_candidates(),
        "ollama_model": ollama_model_name(),
        "provider": provider,
        "orchestrator": "rest",
        "api_version": os.getenv("GEMINI_API_VERSION", "v1alpha"),
        "image_format": os.getenv("GEMINI_IMAGE_FORMAT", "jpeg"),
        "image_jpeg_quality": os.getenv("GEMINI_IMAGE_JPEG_QUALITY", "82"),
        "annotated_image_file": str(annotated_image_file),
        "crop_sheet_files": [str(path) for path in crop_sheet_files],
        "element_ids_file": str(element_ids_file),
        "detections_file": str(detections_file),
        "element_ids": element_ids,
        "system_prompt": system_prompt(),
        "batch_logs": batch_logs,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHAT_LOG_FILE.write_text(json.dumps(chat_log, indent=2), encoding="utf-8")
    LLMS_FILE.write_text(json.dumps(semantics, indent=2), encoding="utf-8")
    FINAL_ACTION_BUTTONS_FILE.write_text(
        json.dumps(build_final_action_buttons(detections, semantics), indent=2),
        encoding="utf-8",
    )

    print(f"Saved LLM outputs to {OUTPUT_DIR}")
    # print("\n=== LLM conversation ===")
    # print(f"model: {model_name}")
    # print(f"system: {system_prompt()}")
    # print(f"user: {prompt}")
    # print(f"image: {annotated_image_file}")
    # print(f"crop_sheets: {crop_sheet_files}")
    # print(f"element_ids: {element_ids_file}")
    # print(f"assistant: {content}")
    # print("thinking: Gemini API does not expose hidden reasoning text.")
    # print(f"metadata: {json.dumps(response_json.get('usageMetadata', {}), indent=2)}")


if __name__ == "__main__":
    main()
