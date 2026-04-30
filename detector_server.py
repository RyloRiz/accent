import os
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
os.environ['GRADIO_DEFAULT_LANG'] = 'en'

import base64
import io
import json
import urllib.error
import urllib.request
import gradio as gr
import torch
import cv2
import numpy as np
from PIL import Image
from typing import Any, Dict, Tuple, List
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from rfdetr.detr import RFDETRMedium

# UI Element classes
CLASSES = ['button', 'field', 'heading', 'iframe', 'image', 'label', 'link', 'text']

# Annotation colors are BGR for OpenCV.
LABEL_BG_COLOR = (0, 0, 0)  # Black
LABEL_TEXT_COLOR = (255, 255, 255)  # White
ANNOTATION_COLORS = [
    (0, 255, 0),      # green
    (255, 80, 80),    # blue
    (0, 180, 255),    # orange
    (255, 0, 255),    # magenta
    (255, 255, 0),    # cyan
    (0, 255, 255),    # yellow
]

# Global model variable
model = None

def load_model(model_path: str = "model.pth"):
    """Load RF-DETR model"""
    global model
    if model is None:
        print("Loading RF-DETR model...")
        model = RFDETRMedium(pretrain_weights=model_path, resolution=1600)
        print("Model loaded successfully!")
    return model

def action_from_text(text: str) -> str:
    value = text.lower().strip()
    destructive = ("delete", "remove", "discard", "reset", "cancel subscription")
    submit = ("submit", "save", "apply", "confirm", "done", "send", "create", "add")
    auth = ("log in", "login", "sign in", "sign up", "register")
    navigation = ("continue", "next", "back", "previous", "close", "open", "view")

    if any(word in value for word in destructive):
        return "destructive"
    if any(word in value for word in auth):
        return "authentication"
    if any(word in value for word in submit):
        return "submit_or_confirm"
    if any(word in value for word in navigation):
        return "navigation"
    return "unknown"

def infer_rule_semantics(detection: Dict[str, Any]) -> Dict[str, Any]:
    label = detection.get("text", "")
    class_name = detection.get("class", "")
    action = action_from_text(label)

    if class_name == "button":
        role = action if action != "unknown" else "button_action"
    elif class_name == "field":
        role = "input_field"
    elif class_name == "heading":
        role = "section_heading"
    elif class_name in {"label", "text"}:
        role = "text_context"
    else:
        role = class_name

    return {
        "role": role,
        "likely_action": action,
        "context": "",
        "source": "rules",
    }
def extract_response_text(response: Dict[str, Any]) -> str:
    if response.get("output_text"):
        return response["output_text"]

    chunks = []
    for output in response.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    return "".join(chunks)

def semantic_candidates(detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "index": index,
            "class": item.get("class"),
            "element_id": item.get("element_id"),
            "box": item.get("box"),
        }
        for index, item in enumerate(detections)
        if item.get("class") in {"button", "field", "link"}
    ][:40]

def semantic_prompt(candidates: List[Dict[str, Any]]) -> str:
    return (
        "You enrich UI detections with concise semantics. "
        "Use the provided screenshot and geometry. "
        "Return only valid JSON with this exact shape: "
        '{"items":[{"index":0,"role":"string","likely_action":"string",'
        '"context":"string","confidence":0.0}]}\n\n'
        f"Detections:\n{json.dumps({'detections': candidates}, ensure_ascii=True)}"
    )

def semantic_system_prompt() -> str:
    return (
        "You are a UI semantics analyzer. You receive a screenshot image and a JSON array "
        "of UI detections from an object detector. Each detection has an implicit index by "
        "array position plus fields such as element_id, class, confidence, and box. Use "
        "the screenshot as the source of truth, and use the JSON for precise coordinates. "
        "Do not ask for an "
        "image; it is attached to the user message. Return only valid JSON. Do not include "
        "markdown or commentary. Do not include a state field."
    )

def semantic_user_prompt(detections: List[Dict[str, Any]]) -> str:
    return (
        "Analyze every detection that could benefit from semantics, especially buttons, "
        "links, fields, headings, and labels. Return this exact JSON shape:\n"
        '{"items":[{"index":0,"role":"string","likely_action":"string",'
        '"context":"string","confidence":0.0}]}\n\n'
        "Rules:\n"
        "- index must match the array position in detections.\n"
        "- role should be a concise UI role, such as primary_button, destructive_button, "
        "navigation_link, text_input, section_heading, label, or icon_button.\n"
        "- likely_action should describe what activating or using the element would do.\n"
        "- context should explain nearby relevant screen context in one short phrase.\n"
        "- confidence must be between 0 and 1.\n"
        "- If uncertain, still return your best guess with lower confidence.\n\n"
        f"Full detections JSON:\n{json.dumps({'detections': detections}, ensure_ascii=True)}"
    )

def image_to_base64_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")

def apply_llm_semantics(
    detections: List[Dict[str, Any]],
    parsed: Dict[str, Any],
    source: str,
) -> List[Dict[str, Any]]:
    for semantic_item in parsed.get("items", []):
        index = semantic_item.get("index")
        if isinstance(index, int) and 0 <= index < len(detections):
            detections[index]["semantic"] = {
                "role": str(semantic_item.get("role", "")),
                "likely_action": str(semantic_item.get("likely_action", "")),
                "context": str(semantic_item.get("context", "")),
                "confidence": round(float(semantic_item.get("confidence", 0.0)), 4),
                "source": source,
            }

    return detections

def parse_llm_json(raw_response: str) -> Dict[str, Any]:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise

def mark_llm_error(
    detections: List[Dict[str, Any]],
    exc: Exception,
    raw_output: Dict[str, Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    for item in detections:
        item.setdefault("semantic", infer_rule_semantics(item))
        item["semantic"]["llm_error"] = str(exc)
    output = raw_output or {}
    output["error"] = str(exc)
    return detections, output

def enrich_semantics_with_ollama(
    detections: List[Dict[str, Any]],
    image: Image.Image,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not detections:
        return detections, {"skipped": "no detections"}

    model_name = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    llm = ChatOllama(
        model=model_name,
        base_url=base_url,
        format="json",
        temperature=0,
        num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "3000")),
        reasoning=os.getenv("OLLAMA_REASONING", "0") == "1",
    )
    messages = [
        SystemMessage(content=semantic_system_prompt()),
        HumanMessage(content=[
            {"type": "text", "text": semantic_user_prompt(detections)},
            {
                "type": "image_url",
                "image_url": "data:image/png;base64," + image_to_base64_png(image),
            },
        ]),
    ]

    try:
        response = llm.invoke(messages)
        raw_response = response.content if isinstance(response.content, str) else json.dumps(response.content)
        raw_output = {
            "provider": "ollama",
            "orchestrator": "langchain",
            "model": model_name,
            "request_included_image": True,
            "image_size": list(image.size),
            "endpoint": "/api/chat",
            "message": {
                "role": "assistant",
                "content": raw_response,
                **response.additional_kwargs,
            },
            "response_metadata": response.response_metadata,
        }
        parsed = parse_llm_json(raw_response)
    except Exception as exc:
        return mark_llm_error(detections, exc, locals().get("raw_output"))

    raw_output["response"] = raw_response
    raw_output["parsed"] = parsed
    return apply_llm_semantics(detections, parsed, f"ollama:{model_name}"), raw_output

def enrich_semantics_with_openai(
    detections: List[Dict[str, Any]],
    image: Image.Image,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return detections, {"skipped": "OPENAI_API_KEY is not set"}

    candidates = semantic_candidates(detections)
    if not candidates:
        return detections, {"skipped": "no semantic candidates"}

    model_name = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model_name,
        "input": [
            {
                "role": "system",
                "content": (
                    "You enrich UI detections with concise semantics. "
                    "Use only the provided screenshot and geometry. Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": semantic_prompt(candidates),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "ui_semantics",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "index": {"type": "integer"},
                                    "role": {"type": "string"},
                                    "likely_action": {"type": "string"},
                                    "context": {"type": "string"},
                                    "confidence": {"type": "number"},
                                },
                                "required": ["index", "role", "likely_action", "context", "confidence"],
                            },
                        }
                    },
                    "required": ["items"],
                },
            }
        },
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        raw_response = extract_response_text(body)
        parsed = json.loads(raw_response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        return mark_llm_error(detections, exc)

    raw_output = {
        "provider": "openai",
        "model": model_name,
        "response": raw_response,
        "parsed": parsed,
        "openai_metadata": body,
    }
    return apply_llm_semantics(detections, parsed, f"openai:{model_name}"), raw_output

def enrich_semantics_with_llm(
    detections: List[Dict[str, Any]],
    image: Image.Image,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider == "openai":
        return enrich_semantics_with_openai(detections, image)
    return enrich_semantics_with_ollama(detections, image)

def rects_overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int], padding: int = 4) -> bool:
    return not (
        a[2] + padding <= b[0]
        or b[2] + padding <= a[0]
        or a[3] + padding <= b[1]
        or b[3] + padding <= a[1]
    )

def clamp_label_rect(
    x1: int,
    y1: int,
    width: int,
    height: int,
    image_width: int,
    image_height: int,
) -> Tuple[int, int, int, int]:
    x1 = max(0, min(x1, image_width - width - 1))
    y1 = max(0, min(y1, image_height - height - 1))
    return (x1, y1, x1 + width, y1 + height)

def choose_label_rect(
    box: Tuple[int, int, int, int],
    label_width: int,
    label_height: int,
    image_width: int,
    image_height: int,
    used_label_rects: List[Tuple[int, int, int, int]],
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    gap = 8
    candidates = [
        (x1, y1 - label_height - gap),
        (x1, y2 + gap),
        (x2 - label_width, y1 - label_height - gap),
        (x2 - label_width, y2 + gap),
        (x2 + gap, y1),
        (x1 - label_width - gap, y1),
        (x1, y1),
    ]

    clamped = [
        clamp_label_rect(x, y, label_width, label_height, image_width, image_height)
        for x, y in candidates
    ]

    for rect in clamped:
        if not any(rects_overlap(rect, used) for used in used_label_rects):
            return rect

    return min(
        clamped,
        key=lambda rect: sum(1 for used in used_label_rects if rects_overlap(rect, used)),
    )

def draw_detections(
    image: np.ndarray,
    boxes: List[Tuple[int, int, int, int]],
    scores: List[float],
    classes: List[int],
    element_ids: List[str],
    thickness: int = 3,
    font_scale: float = 0.8
) -> np.ndarray:
    """Draw detection boxes and labels on image"""
    img_with_boxes = image.copy()
    image_height, image_width = img_with_boxes.shape[:2]
    used_label_rects = []
    label_specs = []

    for index, (box, score, cls_id, element_id) in enumerate(zip(boxes, scores, classes, element_ids)):
        x1, y1, x2, y2 = map(int, box)
        color = ANNOTATION_COLORS[index % len(ANNOTATION_COLORS)]

        cv2.rectangle(img_with_boxes, (x1, y1), (x2, y2), color, thickness)

        label = element_id
        text_thickness = 4
        pad_x = 10
        pad_y = 8
        (label_width, label_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness=text_thickness
        )
        bg_width = label_width + (pad_x * 2)
        bg_height = label_height + baseline + (pad_y * 2)
        label_rect = choose_label_rect(
            (x1, y1, x2, y2),
            bg_width,
            bg_height,
            image_width,
            image_height,
            used_label_rects,
        )
        used_label_rects.append(label_rect)
        label_specs.append({
            "box": (x1, y1, x2, y2),
            "label": label,
            "label_rect": label_rect,
            "label_width": label_width,
            "label_height": label_height,
            "baseline": baseline,
            "pad_x": pad_x,
            "pad_y": pad_y,
            "text_thickness": text_thickness,
            "color": color,
        })

    for spec in label_specs:
        x1, y1, x2, y2 = spec["box"]
        bg_x1, bg_y1, bg_x2, bg_y2 = spec["label_rect"]
        color = spec["color"]
        anchor = ((x1 + x2) // 2, (y1 + y2) // 2)
        label_anchor = ((bg_x1 + bg_x2) // 2, (bg_y1 + bg_y2) // 2)

        cv2.line(img_with_boxes, label_anchor, anchor, color, max(2, thickness))
        cv2.circle(img_with_boxes, anchor, max(4, thickness * 2), color, -1)

        cv2.rectangle(
            img_with_boxes,
            (bg_x1, bg_y1),
            (bg_x2, bg_y2),
            LABEL_BG_COLOR,
            -1
        )
        cv2.rectangle(
            img_with_boxes,
            (bg_x1, bg_y1),
            (bg_x2, bg_y2),
            color,
            max(2, thickness)
        )
        cv2.putText(
            img_with_boxes,
            spec["label"],
            (bg_x1 + spec["pad_x"], bg_y2 - spec["baseline"] - spec["pad_y"]),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            LABEL_TEXT_COLOR,
            thickness=spec["text_thickness"]
        )

    return img_with_boxes

@torch.inference_mode()
def detect_ui_elements(
    image: Image.Image,
    confidence_threshold: float,
    line_thickness: int,
    use_llm: bool
) -> Tuple[Image.Image, str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Detect UI elements in the uploaded image

    Args:
        image: Input PIL Image
        confidence_threshold: Minimum confidence score for detections
        line_thickness: Thickness of bounding box lines
        use_llm: Whether to call an LLM for semantic enrichment

    Returns:
        Annotated image, detection summary text, and detection data
    """
    try:
        if image is None:
            return None, "Please upload an image first.", [], {}

        # Load model
        model = load_model()

        # Convert PIL to numpy array (RGB)
        img_array = np.array(image)

        # Convert RGB to BGR for OpenCV
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # Run detection (returns supervision Detections object)
        detections = model.predict(img_array, threshold=confidence_threshold)

        # Extract detection data
        filtered_boxes = detections.xyxy  # Bounding boxes in xyxy format
        filtered_scores = detections.confidence  # Confidence scores
        filtered_classes = detections.class_id  # Class IDs
        detection_data = []

        for index, (box, score, cls_id) in enumerate(zip(filtered_boxes, filtered_scores, filtered_classes)):
            class_id = int(cls_id)
            class_name = CLASSES[class_id] if 0 <= class_id < len(CLASSES) else f"unknown_{class_id}"
            detection_data.append({
                "element_id": f"E{index}",
                "class": class_name,
                "class_id": class_id,
                "confidence": round(float(score), 4),
                "box": [round(float(coord), 2) for coord in box.tolist()],
                "box_format": "xyxy",
            })

        raw_llm_output = {"skipped": "LLM enrichment disabled"}

        if use_llm:
            detection_data, raw_llm_output = enrich_semantics_with_llm(detection_data, image)

        # Draw detections
        annotated_img = draw_detections(
            img_bgr,
            filtered_boxes.tolist(),
            filtered_scores.tolist(),
            filtered_classes.tolist(),
            [detection["element_id"] for detection in detection_data],
            thickness=line_thickness
        )

        # Convert back to RGB for display
        annotated_img_rgb = cv2.cvtColor(annotated_img, cv2.COLOR_BGR2RGB)
        annotated_pil = Image.fromarray(annotated_img_rgb)

        provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        model_name = os.getenv("OPENAI_MODEL", "gpt-4.1-mini") if provider == "openai" else os.getenv("OLLAMA_MODEL", "gemma4:e2b")
        llm_status = f"{provider}:{model_name}" if use_llm else "skipped"

        # Create summary text
        summary_text = (
            f"**Total detections:** {len(filtered_boxes)}\n\n"
            f"**LLM enrichment:** {llm_status}"
        )

        return annotated_pil, summary_text, detection_data, raw_llm_output

    except Exception as e:
        import traceback
        error_msg = f"**Error during detection:**\n\n```\n{str(e)}\n\n{traceback.format_exc()}\n```"
        print(error_msg)  # Also print to logs
        return None, error_msg, [], {}

# Gradio interface
with gr.Blocks(title="Accent UI Element Detector", theme=gr.themes.Soft()) as demo:

    gr.Markdown("""
    # Accent UI Element Detector

    Upload a screenshot or UI mockup to automatically detect elements.
    """)

    with gr.Row():
        with gr.Column(scale=1):
            input_image = gr.Image(
                type="pil",
                label="Upload Screenshot",
                height=400,
                sources=["upload"]
            )

            with gr.Accordion("Detection Settings", open=True):
                confidence_slider = gr.Slider(
                    minimum=0.1,
                    maximum=0.9,
                    value=0.35,
                    step=0.05,
                    label="Confidence Threshold",
                    info="Higher values = fewer but more confident detections"
                )

                thickness_slider = gr.Slider(
                    minimum=1,
                    maximum=6,
                    value=2,
                    step=1,
                    label="Box Line Thickness"
                )

                llm_checkbox = gr.Checkbox(
                    value=os.getenv("USE_LLM", "1") != "0",
                    label="Use LLM semantic enrichment"
                )

            detect_button = gr.Button("Detect Elements", variant="primary", size="lg")

        with gr.Column(scale=1):
            output_image = gr.Image(
                type="pil",
                label="Detected Elements",
                height=400
            )

            summary_output = gr.Markdown(label="Detection Summary")

            detections_output = gr.JSON(label="Detection Data")

            raw_llm_output = gr.JSON(label="Raw LLM Output")


    # Connect button
    detect_button.click(
        fn=detect_ui_elements,
        inputs=[input_image, confidence_slider, thickness_slider, llm_checkbox],
        outputs=[output_image, summary_output, detections_output, raw_llm_output]
    )

# Launch
if __name__ == "__main__":
    demo.queue().launch(
        share=False,
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )
