from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.getenv("PIPELINE_ENV_FILE", str(PROJECT_DIR / ".env")))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "test_outputs"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = PROJECT_DIR / OUTPUT_DIR

CACHE_FILE = OUTPUT_DIR / "pipeline_cache.json"
REQUIRED_CACHED_FILES = [
    OUTPUT_DIR / "annotated_image.png",
    OUTPUT_DIR / "input_image.png",
    OUTPUT_DIR / "detections.json",
    OUTPUT_DIR / "element_ids.json",
    OUTPUT_DIR / "llms.json",
    OUTPUT_DIR / "final_action_buttons.json",
]


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


def bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def screenshot_path() -> Optional[Path]:
    value = os.getenv("TEST_IMAGE") or os.getenv("SCREENSHOT_PATH")
    return Path(value).expanduser() if value else None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_fingerprint(image_hash: str) -> dict:
    return {
        "source_image_sha256": image_hash,
        "confidence_threshold": os.getenv("CONFIDENCE_THRESHOLD", "0.1"),
        "llm_provider": os.getenv("LLM_PROVIDER", "gemini"),
        "intent_provider": os.getenv("INTENT_PROVIDER", os.getenv("LLM_PROVIDER", "gemini")),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview"),
        "gemini_fallback_model": os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-pro-preview"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "gemma4:e4b"),
        "ollama_intent_model": os.getenv("OLLAMA_INTENT_MODEL", os.getenv("OLLAMA_MODEL", "gemma4:e4b")),
        "crop_sheets_per_llm_call": os.getenv("CROP_SHEETS_PER_LLM_CALL", "4"),
        "max_ids_per_llm_call": os.getenv("MAX_IDS_PER_LLM_CALL", "150"),
        "gemini_image_format": os.getenv("GEMINI_IMAGE_FORMAT", "jpeg"),
    }


def cached_semantics_are_fresh(image_hash: str) -> bool:
    if bool_env("FORCE_FULL_PIPELINE"):
        return False
    if not CACHE_FILE.exists():
        return False
    if any(not path.exists() for path in REQUIRED_CACHED_FILES):
        return False
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return cache == cache_fingerprint(image_hash)


def write_cache(image_hash: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache_fingerprint(image_hash), indent=2), encoding="utf-8")


def run_step(script_name: str) -> None:
    start = time.perf_counter()
    print(f"\n=== Running {script_name} ===")
    subprocess.run(
        [sys.executable, str(PROJECT_DIR / script_name)],
        cwd=PROJECT_DIR,
        check=True,
    )
    print(f"=== Finished {script_name} in {time.perf_counter() - start:.2f}s ===")


def main() -> None:
    load_dotenv(ENV_FILE)
    total_start = time.perf_counter()
    image_path = screenshot_path()
    image_hash = file_sha256(image_path) if image_path and image_path.exists() else None

    if image_hash and cached_semantics_are_fresh(image_hash):
        print("\n=== Reusing cached detector + LLM semantics for unchanged screenshot ===")
    else:
        run_step("test.py")
        run_step("llm.py")
        if image_hash:
            write_cache(image_hash)

    run_step("intent_resolver.py")
    print(f"\nComplete run finished in {time.perf_counter() - total_start:.2f}s.")


if __name__ == "__main__":
    main()
