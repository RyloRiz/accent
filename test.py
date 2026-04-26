from gradio_client import Client, handle_file
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json
import math
import os
import shutil
import sys

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.getenv("PIPELINE_ENV_FILE", str(PROJECT_DIR / ".env")))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "test_outputs"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = PROJECT_DIR / OUTPUT_DIR

INPUT_IMAGE_FILE = OUTPUT_DIR / "input_image.png"
ANNOTATED_IMAGE_FILE = OUTPUT_DIR / "annotated_image.png"
CROP_SHEET_FILES = [OUTPUT_DIR / f"crop_sheet_{index}.png" for index in range(1, 5)]
SUMMARY_FILE = OUTPUT_DIR / "summary.txt"
DETECTIONS_FILE = OUTPUT_DIR / "detections.json"
ELEMENT_IDS_FILE = OUTPUT_DIR / "element_ids.json"
SERVER_URL = os.getenv("GRADIO_SERVER_URL", "http://127.0.0.1:7860/")


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


def default_image_path() -> Path:
    env_image = os.getenv("TEST_IMAGE") or os.getenv("SCREENSHOT_PATH")
    if env_image:
        return Path(env_image).expanduser()
    raise FileNotFoundError("Pass an image path or set TEST_IMAGE in .env.")


def confidence_threshold() -> float:
    value = os.getenv("CONFIDENCE_THRESHOLD", "0.1")
    try:
        threshold = float(value)
    except ValueError as exc:
        raise ValueError(f"CONFIDENCE_THRESHOLD must be a number, got {value!r}") from exc
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"CONFIDENCE_THRESHOLD must be between 0 and 1, got {threshold}")
    return threshold


def crop_sheet_chunks(detections: list[dict]) -> list[list[dict]]:
    chunks = []
    start = 0
    for sheet_index in range(4):
        if start >= len(detections):
            break
        end = len(detections) if sheet_index == 3 else min(start + 50, len(detections))
        chunks.append(detections[start:end])
        start = end
    return chunks


def sheet_title(sheet_number: int, detections: list[dict]) -> str:
    element_ids = [str(detection.get("element_id")) for detection in detections if detection.get("element_id")]
    if not element_ids:
        return f"Crop sheet {sheet_number}"
    if len(element_ids) == 1:
        return f"Crop sheet {sheet_number}: {element_ids[0]}"
    return f"Crop sheet {sheet_number}: {element_ids[0]}-{element_ids[-1]}"


def make_crop_sheet(
    image_path: Path,
    detections: list[dict],
    output_path: Path,
    sheet_number: int,
) -> None:
    tile_width = 260
    tile_height = 220
    label_height = 46
    title_height = 48
    gap = 5
    inner_padding = 8
    cols = 5
    crop_margin = 28

    source = Image.open(image_path).convert("RGB")
    image_width, image_height = source.size
    rows = max(1, math.ceil(len(detections) / cols))
    sheet_width = (cols * tile_width) + ((cols + 1) * gap)
    sheet_height = title_height + (rows * tile_height) + ((rows + 1) * gap)
    sheet = Image.new("RGB", (sheet_width, sheet_height), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("Arial Bold.ttf", 32)
        title_font = ImageFont.truetype("Arial Bold.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rectangle((0, 0, sheet_width, title_height), fill=(0, 0, 0))
    draw.text((12, 8), sheet_title(sheet_number, detections), fill=(255, 255, 255), font=title_font)

    for index, detection in enumerate(detections):
        box = detection.get("box")
        element_id = detection.get("element_id", f"E{index}")
        if not isinstance(box, list) or len(box) != 4:
            continue

        orig_x1, orig_y1, orig_x2, orig_y2 = [int(round(value)) for value in box]
        x1 = max(0, orig_x1 - crop_margin)
        y1 = max(0, orig_y1 - crop_margin)
        x2 = min(image_width, orig_x2 + crop_margin)
        y2 = min(image_height, orig_y2 + crop_margin)
        if x2 <= x1 or y2 <= y1:
            continue

        crop = source.crop((x1, y1, x2, y2))
        crop_draw = ImageDraw.Draw(crop)
        crop_draw.rectangle(
            (orig_x1 - x1, orig_y1 - y1, orig_x2 - x1, orig_y2 - y1),
            outline=(255, 0, 0),
            width=max(3, min(crop.size) // 30),
        )
        crop.thumbnail(
            (tile_width - inner_padding, tile_height - label_height - inner_padding),
            Image.Resampling.LANCZOS,
        )

        row = index // cols
        col = index % cols
        tile_x = gap + col * (tile_width + gap)
        tile_y = title_height + gap + row * (tile_height + gap)

        draw.rectangle(
            (tile_x, tile_y, tile_x + tile_width, tile_y + tile_height),
            fill=(245, 245, 245),
            outline=(0, 255, 0),
            width=3,
        )
        draw.rectangle(
            (tile_x, tile_y, tile_x + tile_width, tile_y + label_height),
            fill=(0, 0, 0),
        )
        draw.text((tile_x + 10, tile_y + 6), str(element_id), fill=(255, 255, 255), font=font)

        crop_x = tile_x + (tile_width - crop.width) // 2
        crop_y = tile_y + label_height + ((tile_height - label_height - crop.height) // 2)
        sheet.paste(crop, (crop_x, crop_y))

    sheet.save(output_path)


load_dotenv(ENV_FILE)

image_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else default_image_path()

if not image_path.exists():
    raise FileNotFoundError(f"Image not found: {image_path}")

client = Client(SERVER_URL)
annotated_image, summary, detections, _ = client.predict(
    image=handle_file(str(image_path)),
    confidence_threshold=confidence_threshold(),
    line_thickness=1,
    use_llm=False,
    api_name="/detect_ui_elements",
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
for stale_file in (
    OUTPUT_DIR / "semantics.json",
    OUTPUT_DIR / "raw_gemma_output.json",
    OUTPUT_DIR / "llm_chat_log.json",
    OUTPUT_DIR / "llms.json",
    OUTPUT_DIR / "final_action_buttons.json",
    OUTPUT_DIR / "conflict_resolution.json",
    OUTPUT_DIR / "crop_sheet.png",
    *CROP_SHEET_FILES,
):
    stale_file.unlink(missing_ok=True)

element_ids = [
    detection["element_id"]
    for detection in detections
    if isinstance(detection, dict) and detection.get("element_id")
]

shutil.copyfile(image_path, INPUT_IMAGE_FILE)
shutil.copyfile(annotated_image, ANNOTATED_IMAGE_FILE)
for sheet_number, (crop_sheet_file, chunk) in enumerate(zip(CROP_SHEET_FILES, crop_sheet_chunks(detections)), 1):
    make_crop_sheet(image_path, chunk, crop_sheet_file, sheet_number)
SUMMARY_FILE.write_text(summary, encoding="utf-8")
DETECTIONS_FILE.write_text(json.dumps(detections, indent=2), encoding="utf-8")
ELEMENT_IDS_FILE.write_text(json.dumps(element_ids, indent=2), encoding="utf-8")

print(f"Saved detector outputs and crop sheets to {OUTPUT_DIR} from {SERVER_URL}")
