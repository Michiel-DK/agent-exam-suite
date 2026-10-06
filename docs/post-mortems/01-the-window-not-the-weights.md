# Post-mortem 1 — The window, not the weights (July–September 2026)

**What we believed.** A 7,597-character meeting digest errored on the local 4B model. The obvious write-up was "gemma4 can't
handle long inputs", and it would have gone into the model notes that feed the routing table, so a future session would have
routed long inputs away from that model.

**What the probe showed.** The call died at exactly 4,096 tokens. Ollama's OpenAI-compatible endpoint, the one the runner used,
runs every model at a 4,096-token window and silently **ignores** the `num_ctx` option in the request: the output was
byte-identical with and without it, and `ollama ps` still reported `CONTEXT 4096`. Only the native API honours it. Past about
3,000 prompt tokens the front of the prompt is cut, system prompt first, and the model answers confidently on what is left,
or dies with `finish_reason=length` and zero content.

Three separate measurements had already read that truncation as a capability verdict before anyone checked: a multi-turn CRM
exam scored 0 of 4 (two of the four were the window), a transcript model was "dead on every real-length call" (a 19.6k-character
call is 5,317 tokens), and an 8B model was "dead on the whole long band" (it had run at its 4k default).

**What changed.** The window became a champion field, set through a Modelfile (`PARAMETER num_ctx 16384` → `<model>-ctx16k`),
operator-signed, at about +85% wall time. A rule entered the project file: *every verdict on an input over ~3k tokens is a
verdict about the window until the window is stated.* And a second, quieter finding: at 8,192 and 16,384 the digest case
completes and still fails the same check, so the window bought **attribution, not capability** — the compression failure was
the real finding, the context ceiling was incidental.

**The transferable rule.** When a failure has an obvious infrastructural explanation, measure it before it becomes a capability
claim. An ad-hoc probe outside the tool is not a witness for the tool; reproduce through the real entry point.
