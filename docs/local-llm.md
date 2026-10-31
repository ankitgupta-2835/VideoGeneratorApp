# Running the pipeline with a local or alternative LLM

The agents only need an OpenAI-compatible `/chat/completions` API. Set
`LLM_PROVIDER=openai` and point `LLM_BASE_URL` at whatever serves it — a hosted
free tier or a model running inside the same notebook.

This is the escape hatch for:

- Gemini **503 / "high demand"** spikes and retired models.
- Free-tier rate limits and quota exhaustion.
- Running fully offline on Kaggle/Colab GPUs.

## Option 1 — hosted, no GPU (fastest to try)

| Host | `LLM_BASE_URL` | Key | Notes |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` (or `LLM_PROVIDER=groq`) | Fastest; strict free TPM limits |
| Cerebras | `https://api.cerebras.ai/v1` | `OPENAI_API_KEY` | Very fast, free tier |
| GitHub Models | `https://models.github.ai/inference` | `OPENAI_API_KEY` (a GitHub PAT) | Free with rate limits |
| Mistral | `https://api.mistral.ai/v1` | `OPENAI_API_KEY` | Free experiment tier |

`.env` for Groq through the generic path:

```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=gsk_...
LLM_MODEL=llama-3.3-70b-versatile
```

(The same host is also available as `LLM_PROVIDER=groq` + `GROQ_API_KEY`.)

Check which models a host offers:

```python
import os, httpx
r = httpx.get(f"{os.environ['LLM_BASE_URL']}/models",
              headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
print([m["id"] for m in r.json().get("data", [])])
```

## Option 2 — a real local model on a Kaggle GPU

Kaggle gives ~30 GPU-hours/week (2×T4 or P100, 16 GB each). Serve a 7B model
with vLLM and run the pipeline against `localhost` in the same notebook.

**Cell 1 — install and start the server** (runs in the background):

```python
!pip install -q vllm
import subprocess, sys, time, httpx

proc = subprocess.Popen([
    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
    "--model", "Qwen/Qwen2.5-7B-Instruct",
    "--port", "8000",
    "--max-model-len", "8192",
    "--gpu-memory-utilization", "0.90",
])

for _ in range(120):
    try:
        if httpx.get("http://localhost:8000/v1/models", timeout=2).status_code == 200:
            print("server ready")
            break
    except Exception:
        pass
    time.sleep(5)
else:
    raise RuntimeError("vLLM did not start")
```

**Cell 2 — point the pipeline at it:**

```python
import os
os.environ["LLM_PROVIDER"] = "openai"
os.environ["LLM_BASE_URL"] = "http://localhost:8000/v1"
os.environ["OPENAI_API_KEY"] = "local"          # any non-empty value
os.environ["LLM_MODEL"] = "Qwen/Qwen2.5-7B-Instruct"
os.environ["HTTP_TIMEOUT"] = "180"              # local generation is slower
```

**Cell 3 — run:**

```python
%cd /kaggle/working/videogen
!git pull
!python -m src.pipeline --category ai_tech --demo --max-scenes 4
```

### Model and hardware notes

- **7B fp16 (~14 GB)** fits one T4 with an 8k context. 14B fp16 does **not**;
  use a 4-bit AWQ/GPTQ checkpoint (e.g. `Qwen/Qwen2.5-14B-Instruct-AWQ`) on one
  GPU, or `--tensor-parallel-size 2`.
- Kaggle sessions are ephemeral: the weights re-download every session. For
  repeat use, upload the model once as a Kaggle Dataset and pass its path to
  `--model`.
- Local 7B models are noticeably weaker at strict JSON and long scripts. Expect
  more `rework`/`fail` at `script`/`localize`; keep `--max-scenes` low.
- Ollama on Kaggle **CPU** works but is far too slow for a multi-stage video
  pipeline; use a GPU server (vLLM) or a hosted endpoint.

## Verifying without running the pipeline

```python
import os, httpx
r = httpx.post(f"{os.environ['LLM_BASE_URL']}/chat/completions",
               headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
               json={"model": os.environ["LLM_MODEL"],
                     "messages": [{"role": "user", "content": "Reply with {\"ok\": true}"}],
                     "response_format": {"type": "json_object"}},
               timeout=180)
print(r.status_code, r.text[:300])
```

If this returns a JSON object, the pipeline's `angle` stage will be able to talk
to the endpoint too.

## Reminder

Whichever backend you choose, the other stages (voice, visuals, assembly) are
unchanged. Local LLMs remove the LLM quota problem, not the FFmpeg/TTS work.
