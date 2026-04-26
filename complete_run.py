from pathlib import Path
import subprocess
import sys

PROJECT_DIR = Path(__file__).resolve().parent


def run_step(script_name: str) -> None:
    print(f"\n=== Running {script_name} ===")
    subprocess.run(
        [sys.executable, str(PROJECT_DIR / script_name)],
        cwd=PROJECT_DIR,
        check=True,
    )


def main() -> None:
    run_step("test.py")
    run_step("llm.py")
    run_step("intent_resolver.py")
    print("\nComplete run finished.")


if __name__ == "__main__":
    main()
