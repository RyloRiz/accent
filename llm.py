from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pathlib import Path
from PIL import Image
import base64
import io
import json
import os
import sys

OUTPUT_DIR = Path("/Users/kaartiktejwani/UCLA Files/Playground Code/UI-DETR-1/test_outputs")
DEFAULT_IMAGE_FILE = OUTPUT_DIR / "input_image.png"
DEFAULT_DETECTIONS_FILE = OUTPUT_DIR / "detections.json"
CHAT_LOG_FILE = OUTPUT_DIR / "llm_chat_log.json"
SEMANTICS_FILE = OUTPUT_DIR / "llm_semantics.json"
MAX_DETECTIONS = int(os.getenv("LLM_MAX_DETECTIONS", "40"))


def image_to_base64_png(image_path: Path) -> str:
    with Image.open(image_path) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def system_prompt() -> str:
    return (
        "You are a UI semantics analyzer. You receive one screenshot image and one JSON "
        "array of detections produced by a UI object detector plus OCR/spatial matching. "
        "Use the screenshot as visual ground truth. Use the JSON for exact boxes, class "
        "labels, OCR text, matched OCR, and nearby text. Do not ask for the image; it is "
        "attached in the same user message. Return only valid JSON. Do not include markdown. "
        "Do not include a state field."
    )


def user_prompt(detections: list) -> str:
    return (
        "Analyze the screenshot and the full detections JSON. Add semantic meaning for "
        "UI elements, especially buttons, links, fields, headings, labels, and icon-like "
        "controls.\n\n"
        "Return exactly this JSON shape:\n"
        '{"items":[{"index":0,"role":"string","likely_action":"string",'
        '"context":"string","confidence":0.0}]}\n\n'
        "Rules:\n"
        "- Do not echo or copy the detections input JSON.\n"
        "- The only top-level key in your response must be items.\n"
        "- index must match the array index in detections.\n"
        "- role should be concise, e.g. primary_button, destructive_button, navigation_link, "
        "text_input, section_heading, label, icon_button, image, text_block.\n"
        "- likely_action should describe what the user expects if they click/type/use it.\n"
        "- context should be a short phrase from the visible screen context.\n"
        "- confidence must be between 0 and 1.\n"
        "- Include every detection in the compact detections list.\n"
        "- If the detector/OCR is uncertain, still give the best guess with lower confidence.\n\n"
        f"Compact detections JSON:\n{json.dumps({'detections': detections}, ensure_ascii=True)}"
    )


def detection_priority(detection: dict) -> int:
    class_name = detection.get("class", "")
    text = detection.get("text", "")
    nearby_text = detection.get("nearby_text", [])

    if class_name in {"button", "field", "link", "heading"}:
        return 0
    if text:
        return 1
    if nearby_text:
        return 2
    if class_name in {"label", "text"}:
        return 3
    return 4


def compact_detections(detections: list) -> list:
    indexed = [
        {
            "index": index,
            "element_id": detection.get("element_id", f"E{index}"),
            "class": detection.get("class"),
            "confidence": detection.get("confidence"),
            "box": detection.get("box"),
            "text": detection.get("text", ""),
            "nearby_text": detection.get("nearby_text", [])[:5],
            "matched_text": [item.get("text", "") for item in detection.get("matched_ocr", [])[:3]],
            "rule_semantic": detection.get("semantic", {}),
            "_priority": detection_priority(detection),
        }
        for index, detection in enumerate(detections)
    ]
    indexed.sort(key=lambda item: (item["_priority"], -float(item.get("confidence") or 0)))
    compact = indexed[:MAX_DETECTIONS]
    compact.sort(key=lambda item: item["index"])

    for item in compact:
        item.pop("_priority", None)

    return compact


def parse_json_response(content: str) -> dict:
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
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(text[start:end + 1])
        else:
            raise

    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise ValueError("LLM response did not match expected schema with top-level items list.")
    return parsed


def main() -> None:
    image_file = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_IMAGE_FILE
    detections_file = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else DEFAULT_DETECTIONS_FILE

    if not image_file.exists():
        raise FileNotFoundError(f"Image file not found: {image_file}")
    if not detections_file.exists():
        raise FileNotFoundError(f"Detections file not found: {detections_file}")

    detections = json.loads(detections_file.read_text(encoding="utf-8"))
    compact = compact_detections(detections)
    image_b64 = image_to_base64_png(image_file)
    model_name = os.getenv("OLLAMA_MODEL", "gemma4:e2b")

    messages = [
        SystemMessage(content=system_prompt()),
        HumanMessage(content=[
            {"type": "text", "text": user_prompt(compact)},
            {"type": "image_url", "image_url": "data:image/png;base64," + image_b64},
        ]),
    ]

    llm = ChatOllama(
        model=model_name,
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        format="json",
        temperature=0,
        num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "32768")),
        num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "6000")),
        reasoning=os.getenv("OLLAMA_REASONING", "0") == "1",
    )

    response = llm.invoke(messages)
    content = response.content if isinstance(response.content, str) else json.dumps(response.content)

    chat_log = {
        "model": model_name,
        "orchestrator": "langchain",
        "image_file": str(image_file),
        "detections_file": str(detections_file),
        "input_detection_count": len(detections),
        "sent_detection_count": len(compact),
        "sent_detection_indexes": [item["index"] for item in compact],
        "messages": [
            {"role": "system", "content": system_prompt()},
            {
                "role": "user",
                "content": user_prompt(compact),
                "image_base64_png": image_b64,
            },
            {
                "role": "assistant",
                "content": content,
                "additional_kwargs": response.additional_kwargs,
                "response_metadata": response.response_metadata,
            },
        ],
    }

    try:
        semantics = parse_json_response(content)
    except (json.JSONDecodeError, ValueError) as exc:
        semantics = {
            "items": [],
            "error": str(exc),
            "raw_content": content,
        }

    OUTPUT_DIR.mkdir(exist_ok=True)
    CHAT_LOG_FILE.write_text(json.dumps(chat_log, indent=2), encoding="utf-8")
    SEMANTICS_FILE.write_text(json.dumps(semantics, indent=2), encoding="utf-8")

    print(f"Saved LLM outputs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
