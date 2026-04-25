---
title: UI-DETR-1
emoji: 🏢
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 5.47.2
app_file: app.py
pinned: false
license: mit
models:
  - racineai/UI-DETR-1
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference




<!-- # Clone repository
git clone https://huggingface.co/spaces/racineai/UI-DETR-1
cd UI-DETR-1 -->

# Create and activate Python environment
python -m venv env
source env/bin/activate

# Install dependencies and run
pip install -r requirements.txt
python app.py


To test:
Step 1: 
```
python3 app.py
```

Open new terminal. Run:
```
python3 test.py 'img_path'
```

Need ollama and gemma4:e2b install
```
ollama list
ollama pull gemma4:e2b
```
Run for semantic embadding done via lanagchain (og base image passed plus detections json)
```
python3 llm.py
```