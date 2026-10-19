# E2 local chat-model comparison

Recorded 2026-10-19. This is the E2 measurement record. The local JSON reports
and the blinded staff-question sheet live under Git-ignored `data/extracted/`;
they may contain internal conversation text and should only be shared with an
authorized reviewer.

## Fixed comparison conditions

- Hardware: AMD Ryzen 3 3250U, two cores/four threads, about 13 GiB RAM, no
  discrete GPU. The existing embedding model and collection remain
  `qwen3-embedding:0.6b` and `sardars_public_qwen3_embedding_06b_v1`.
- Preserved original evaluation corpus: 1,000 registered sources, 3,765
  Qdrant points, 4,983 product rows. The PostgreSQL authorization/product-fact
  fingerprint before model comparison is
  `c297f43e74e59bb7ae9adb7e42e97b96d9859c9b703e46b72b4b7745ed3fd3ad`.
  The full Qdrant point/vector/payload fingerprint is
  `b503e6f3e85b31dbb3fcb4a6c11c061dcf9a5d91dde456e499d9eb798f194767`.
- The 26 chat cases and 40 full-site cases are unchanged; their SHA-256 hashes
  are `2253fd9e78a3a89b89d87af42ea2ffb53209c8f23ded085c249c4d1cca07c45c`
  and `d546fda0e52ba9db871826a038966903b12f61f69634b6b88a978c4d7349d17e`.
  Prompts, routing, authorization, registered tools, retrieval limits, answer
  deadline (90 seconds), and generation cap (256 tokens) were not tuned between
  model runs. Git revision at the baseline was
  `e654e5bb140453758b064532bf6d337983b12030`; the E2 helper files added
  afterward do not change runtime answer behavior.
- Existing model: `qwen3:0.6b`, Ollama digest `7df6b6e09427`, Q4_K_M.
  The 4B candidate is [Unsloth's Qwen3-4B-Instruct-2507 Q4_K_M
  GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/blob/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf), pinned to revision
  `1e1094e82febb22ad75c2802fc1cbc94c74f8481`. Its downloaded 2,497,281,120-byte
  file passed SHA-256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`.
  It was imported with the official Ollama `qwen3:4b-instruct-2507-q4_K_M`
  chat template and parameter layers (verified layer hashes) under local tag
  `sardars-e2-qwen3-4b-instruct:latest`. This is a local import of the same
  model family/quantization, not the official Ollama weight blob.

## Candidate acquisition and smoke check

The Git-ignored GGUF is at
`data/extracted/e2_model_download/Qwen3-4B-Instruct-2507-Q4_K_M.gguf`.
Ollama's installed copy is in Docker volume `sardars-e2_ollama_data`, mounted
at `/root/.ollama/models` in `sardars-e2-ollama`; the model blob is
`blobs/sha256-3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`.
On this Linux host Docker reports the volume mountpoint as
`/var/lib/docker/volumes/sardars-e2_ollama_data/_data`. The model appeared in
`ollama list` and remained there after restarting the container. A direct
chat returned `READY` with a stop reason; the project Ollama adapter parsed a
`get_product_details(identifier="TEST-2")` tool call in about 28.3 seconds.
Neither check executed a product lookup or measured answer quality. The app
default and the E1 Ollama volume were not changed.

## Current-model baseline before comparison

The original host Ollama 0.40.3 run passed 26/26 chat checks and 7/7 seed
checks; the fixed full-site run passed 34/40, with 21/24 expected sources
present in authorized retrieval. Full-site live median/p95 were 2,663/11,282
ms. The chat median/p95 were 175/8,005 ms, but only one of its 18 live cases
called the model; the other paths were predominantly application routing,
PostgreSQL tools, or evidence selection. The full-site suite called the model
on 19 cases. All eight isolated trust controls passed in both applicable
suites. Reports: `e2_chat_06b_20261019.json`, `e2_seed_06b_20261019.log`,
`e2_fullsite_06b_20261019.json`.

The same six full-site cases remain open: `mirror`, `seat_materials`,
`mirror_paraphrase`, `fittings_materials_article`,
`sustainable_toilets_article`, and `maintenance_article`. The latter three
lack the expected source in authorized retrieval, so model size cannot repair
them. A read-only replay of eight prior internal questions found some
abstentions and incomplete answers with **zero model calls**. Those require
routing, retrieval, or answer-rule work, not just a larger chat model.

The 0.6B and embedding runners occupied about 1.0 and 2.4 GB respectively
while resident on CPU. The host had about 2.7 GiB available RAM and 2.2 GiB
swap in use at that sample; these figures include unrelated host processes.
The `chat_with_tools` adapter parsed an exact-SKU `get_product_details`
request from 0.6B, with `identifier: TEST-2`; this was a shape check only and
did not execute a product tool.

## Same-server comparison and model choice

Both models ran serially through the isolated Ollama 0.12.6 server against the
same unchanged original PostgreSQL/Qdrant corpus. The 26 chat cases, seven seed
cases, 40 full-site cases and eight saved staff questions were repeated without
changing prompts, routing, tools, generation cap or answer deadline. The earlier
host-Ollama baseline above remains historical; this is the comparable result:

| Measure | 0.6B | 4B Instruct |
| --- | ---: | ---: |
| Chat checks | 26/26 | 26/26 |
| Seed checks | 7/7 | 7/7 |
| Full-site checks | 34/40 | 34/40 |
| Expected source in authorized retrieval | 21/24 | 21/24 |
| Full-site live median / nearest-rank p95 | 3,619 / 17,083 ms | 14,843 / 43,557 ms |
| Nineteen model-invoking full-site turns: median / p95 | 5,921 / 19,122 ms | 19,429 / 48,638 ms |
| One model-invoking saved staff turn | 12,307 ms | 41,571 ms |

The same six full-site cases failed under both models: `mirror`,
`seat_materials`, `mirror_paraphrase`, `fittings_materials_article`,
`sustainable_toilets_article` and `maintenance_article`. Both retained all
eight synthetic permission/source-trust controls, 18/18 chat-route checks and
the exact PostgreSQL fact checks. No evaluated turn timed out. The chat suite
invoked the model only once; that turn took 19,230 ms with 0.6B and 35,387 ms
with 4B. Most product and out-of-scope answers did not call the model, so their
faster wall time in one run is not evidence that 4B generates faster.

The blinded packet of eight real staff questions, saved locally as
`e2_staff_blind_packet_20261019.md` with a separate key, had **identical answer
text and citations for all eight pairs**. They are objective ties; subjective
human scoring of identical text would not distinguish the models; the developer
confirmed that these exact ties may close E2's blind comparison. Eight of 40
full-site answers differed in wording. All eight kept the same citations and
pass outcomes. Six differences only moved the citation marker; the other two
added wording present in the cited catalogue excerpts without a measured
quality gain. This
is a limited review, not independent human approval of model quality. A human
review with richer post-ingestion staff cases remains useful after E4.

During the 4B run the Ollama container used about 5.7 GiB while chat and
embedding work were resident; `ollama ps` listed 3.5 GB for 4B and 1.4 GB
for the embedding model after the run. With 4B unloaded, the same server
listed 1.0 GB for 0.6B plus 1.4 GB for embeddings, and the container used
about 2.3 GiB. The host had 1.2 GiB swap in use during these samples, which
also includes unrelated processes. The 4B direct free-form pregnancy example
supplied by the developer took 329 seconds for 953 tokens and bypassed the
application's scope checks; it is not a company-answer quality result. A
separate read-only routing check found that the exact misspelling `pregnency`
is classified as `company` rather than `health`; this known scope-routing gap
was not changed during the frozen E2 comparison. An 8B
model was not run because 4B already raised model-invoking latency about
threefold on this CPU without improving the fixed quality scores.

**Decision:** the developer selected 4B for the current machine despite its
measured latency cost and unchanged automated quality score. The local Docker
application now reads `SARDARS_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M`
from its Git-ignored `.env`; the tested GGUF and official Ollama chat template
were installed under that tag in the app's persistent
`sardars-e1_e1_ollama_data` volume. The standalone E2 volume retains the
comparison copy. The model-init service found the installed tag, the API and
web became healthy, and the API container's Ollama adapter returned `READY`
from the 4B tag in 11,982 ms. Authenticated UI chat was not rerun as part of
this selection change. The shared code fallback remains 0.6B for environments
without the local `.env` selection; a new machine must set this variable and
let Compose pull or import the selected 4B model.

This is a developer preference, not an inference that the 4B weights performed
better on the measured Sardars cases. Retrieval and application routing
determined many answers, and the fixed dataset showed no correctness gain.
Re-evaluate its usability after richer Sardars ingestion or on stronger
hardware. This choice does not clear the six full-site failures or the Phase 5
full-corpus retrieval regressions.

Evidence: `e2_chat_06b_same_server_20261019.json`, `e2_chat_4b_20261019.json`,
`e2_seed_06b_same_server_20261019.log`, `e2_seed_4b_20261019.log`,
`e2_fullsite40_06b_same_server_20261019.json`,
`e2_fullsite40_4b_20261019.json`, `e2_staff_06b_same_server_20261019.json`,
and `e2_staff_4b_20261019.json` under Git-ignored `data/extracted/`.
Post-run PostgreSQL and full Qdrant fingerprints exactly matched the frozen
values above. Focused E2 tests passed 38/38. The staff replay was read-only
and standalone: it omitted conversation history, HTTP auth and UI behavior;
application authorization and role/source visibility still applied. It did
not assess saved-conversation follow-up context. Product-handle follow-up
checks passed in the 26-case suite.
