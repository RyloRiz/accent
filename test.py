from gradio_client import Client, handle_file
from pathlib import Path
import json
import os
import shutil
import sys

OUTPUT_DIR = Path("/Users/kaartiktejwani/UCLA Files/Playground Code/UI-DETR-1/test_outputs")
INPUT_IMAGE_FILE = OUTPUT_DIR / "input_image.png"
ANNOTATED_IMAGE_FILE = OUTPUT_DIR / "annotated_image.png"
SUMMARY_FILE = OUTPUT_DIR / "summary.txt"
DETECTIONS_FILE = OUTPUT_DIR / "detections.json"
SERVER_URL = os.getenv("GRADIO_SERVER_URL", "http://127.0.0.1:7860/")


def default_image_path() -> Path:
    matches = sorted(Path("/Users/kaartiktejwani/Desktop").glob("Screenshot 2026-04-25 at 1.16.42*PM.png"))
    if matches:
        return matches[0]
    return Path("/Users/kaartiktejwani/Desktop/Screenshot 2026-04-25 at 1.16.42 PM.png")


image_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else default_image_path()

if not image_path.exists():
    raise FileNotFoundError(f"Image not found: {image_path}")

client = Client(SERVER_URL)
annotated_image, summary, detections, _ = client.predict(
    image=handle_file(str(image_path)),
    confidence_threshold=0.5,
    line_thickness=5,
    use_llm=False,
    api_name="/detect_ui_elements",
)

OUTPUT_DIR.mkdir(exist_ok=True)
for stale_file in (
    OUTPUT_DIR / "semantics.json",
    OUTPUT_DIR / "raw_gemma_output.json",
    OUTPUT_DIR / "llm_chat_log.json",
    OUTPUT_DIR / "llm_semantics.json",
):
    stale_file.unlink(missing_ok=True)

shutil.copyfile(image_path, INPUT_IMAGE_FILE)
shutil.copyfile(annotated_image, ANNOTATED_IMAGE_FILE)
SUMMARY_FILE.write_text(summary, encoding="utf-8")
DETECTIONS_FILE.write_text(json.dumps(detections, indent=2), encoding="utf-8")

print(f"Saved detector/OCR outputs to {OUTPUT_DIR} from {SERVER_URL}")
