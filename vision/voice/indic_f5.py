"""IndicF5 (AI4Bharat) run natively in MLX on Apple silicon: the voice-cloning engine for Mani's own voice.

Vendored from indic-f5-mlx 0.1.0 by Yogen Ghodke (MIT), https://huggingface.co/yogenghodke/indic-f5-mlx, read before use;
it adapts lucasnewman/f5-tts-mlx (MIT). The weights are ai4bharat/IndicF5 (MIT, gated: the terms are accepted on its
Hugging Face page and `hf auth login` is run once; they are downloaded then, never kept in this repo).
The original notes follow.

IndicF5-MLX: run AI4Bharat's IndicF5 text-to-speech natively in MLX on Apple Silicon.

IndicF5 is a fine-tune of **F5-TTS (v0 / F5TTS_Base)**. lucasnewman/f5-tts-mlx ports
**F5-TTS v1**. The architectures are identical in *shape*, so weights load cleanly — but
there is one behavioral difference that silently corrupts output:

    RoPE application order.
      * F5 v0 (IndicF5): apply rotary embedding to q/k BEFORE splitting into heads.
      * F5 v1 (f5-tts-mlx): apply it AFTER splitting into heads.

With v1's order, IndicF5 produces speech-like but wrong-language gibberish (the acoustic
DiT is fine; the attention positions are scrambled so the model ignores the text).
`patch_f5_rope_to_v0()` restores the v0 order at runtime — a numerically-verified fix
(per-layer diff vs the PyTorch reference drops from ~38 to ~0.008).

Other IndicF5-specific settings handled here:
  * text_mask_padding=False   (v0 has no text-padding masking)
  * text_num_embeds=len(vocab) (IndicF5's vocab.txt line-count convention)
  * skip the checkpoint's bundled `vocoder.*` tensors (we use the native MLX vocos)
  * strip the `ema_model.` and torch.compile `_orig_mod.` key prefixes
  * DO NOT run text through convert_char_to_pinyin (raw char tokenization matches training)
"""
from __future__ import annotations
import os
import glob
from pathlib import Path

import numpy as np
import mlx.core as mx

import f5_tts_mlx.dit as _dit
from f5_tts_mlx.rope import apply_rotary_pos_emb


# ----------------------------------------------------------------------------- #
# The fix: RoPE-before-head-reshape (F5 v0 order)
# ----------------------------------------------------------------------------- #
def _attention_call_v0(self, x, mask=None, rope=None):
    batch, seq_len, _ = x.shape

    query = self.to_q(x)
    key = self.to_k(x)
    value = self.to_v(x)

    # apply rotary embedding BEFORE splitting heads (this is the IndicF5 / F5-v0 order)
    if rope is not None:
        freqs, xpos_scale = rope
        q_xpos_scale, k_xpos_scale = (
            (xpos_scale, xpos_scale**-1.0) if xpos_scale is not None else (1.0, 1.0)
        )
        query = apply_rotary_pos_emb(query, freqs, q_xpos_scale)
        key = apply_rotary_pos_emb(key, freqs, k_xpos_scale)

    query = query.reshape(batch, seq_len, self.heads, -1).transpose(0, 2, 1, 3)
    key = key.reshape(batch, seq_len, self.heads, -1).transpose(0, 2, 1, 3)
    value = value.reshape(batch, seq_len, self.heads, -1).transpose(0, 2, 1, 3)

    attn_mask = mask[:, None, None, :] if mask is not None else None
    out = mx.fast.scaled_dot_product_attention(
        q=query, k=key, v=value, scale=self._scale_factor, mask=attn_mask
    )
    out = out.transpose(0, 2, 1, 3).reshape(batch, seq_len, -1).astype(query.dtype)
    return self.to_out(out)


_ORIGINAL_ATTENTION_CALL = _dit.Attention.__call__


def patch_f5_rope_to_v0():
    """Monkeypatch f5-tts-mlx's Attention to use the F5-v0 RoPE order IndicF5 needs.
    Idempotent. Call once before building/loading an IndicF5 model."""
    _dit.Attention.__call__ = _attention_call_v0


def unpatch_f5_rope():
    """Restore f5-tts-mlx's original (v1) RoPE order."""
    _dit.Attention.__call__ = _ORIGINAL_ATTENTION_CALL


# ----------------------------------------------------------------------------- #
# Weight conversion (PyTorch IndicF5 checkpoint -> MLX), from f5-tts-mlx's mapping
# ----------------------------------------------------------------------------- #
def _convert_indicf5_weights(state_dict):
    out = {}
    for k, v in state_dict.items():
        # IndicF5 stores EMA weights, saved from a torch.compile'd model.
        k = k.replace("ema_model.", "").replace("_orig_mod.", "")
        if (
            len(k) < 1
            or "mel_spec." in k
            or k.startswith("vocoder.")   # bundled vocos — we use the MLX vocos instead
            or k in ("initted", "step")
        ):
            continue
        # module renames to match the MLX nn.Sequential structure
        if ".to_out" in k:
            k = k.replace(".to_out", ".to_out.layers")
        elif ".text_blocks" in k:
            k = k.replace(".text_blocks", ".text_blocks.layers")
        elif ".ff.ff.0.0" in k:
            k = k.replace(".ff.ff.0.0", ".ff.ff.layers.0.layers.0")
        elif ".ff.ff.2" in k:
            k = k.replace(".ff.ff.2", ".ff.ff.layers.2")
        elif ".time_mlp" in k:
            k = k.replace(".time_mlp", ".time_mlp.layers")
        elif ".conv1d" in k:
            k = k.replace(".conv1d", ".conv1d.layers")
        # Conv1d weight layout: PyTorch (out, in/groups, k) -> MLX (out, k, in/groups)
        if (
            k.endswith(".dwconv.weight")
            or k.endswith(".conv1d.layers.0.weight")
            or k.endswith(".conv1d.layers.2.weight")
        ):
            v = v.swapaxes(1, 2)
        out[k] = v
    return out


def _resolve_local_path(repo_id_or_path: str) -> str:
    """Return a local dir containing model.safetensors + checkpoints/vocab.txt,
    downloading from the HF hub if given a repo id."""
    if os.path.isdir(repo_id_or_path):
        return repo_id_or_path
    from huggingface_hub import snapshot_download
    return snapshot_download(repo_id_or_path, allow_patterns=["*.safetensors", "checkpoints/*"])


def load_indicf5(repo_id: str = "ai4bharat/IndicF5", vocoder_repo: str = "lucasnewman/vocos-mel-24khz"):
    """Load IndicF5 as a native MLX model. Returns (f5_model, vocos)."""
    from f5_tts_mlx.cfm import F5TTS
    from f5_tts_mlx.dit import DiT
    from vocos_mlx import Vocos

    patch_f5_rope_to_v0()

    path = _resolve_local_path(repo_id)
    vocab_path = os.path.join(path, "checkpoints", "vocab.txt")
    # IndicF5's line-order char vocab; space is index 0
    vocab = {v: i for i, v in enumerate(Path(vocab_path).read_text().split("\n"))}

    ckpt = glob.glob(os.path.join(path, "model.safetensors"))
    if not ckpt:
        raise FileNotFoundError(f"model.safetensors not found in {path}")

    vocos = Vocos.from_pretrained(vocoder_repo)
    model = F5TTS(
        transformer=DiT(
            dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4,
            text_num_embeds=len(vocab),      # IndicF5 vocab convention
            text_mask_padding=False,         # F5 v0: no text-padding masking
        ),
        vocab_char_map=vocab,
        vocoder=vocos.decode,
    )
    weights = _convert_indicf5_weights(mx.load(ckpt[0], format="safetensors"))
    model.load_weights(list(weights.items()))
    mx.eval(model.parameters())
    return model, vocos


# ----------------------------------------------------------------------------- #
# Inference
# ----------------------------------------------------------------------------- #
def generate(
    model,
    ref_audio_path: str,
    ref_text: str,
    text: str,
    steps: int = 16,
    cfg_strength: float = 2.0,
    sway_sampling_coef: float = -1.0,
    target_rms: float = 0.1,
    speed: float = 1.0,
    seed: int | None = None,
):
    """Synthesize `text` in the voice of the 24 kHz mono reference clip.

    IndicF5 is a zero-shot voice cloner: `ref_audio_path` sets the voice, `ref_text`
    is its transcript. Numbers should be spelled out as words (IndicF5 doesn't read
    digit strings). Returns a float32 numpy waveform at 24 kHz.
    """
    import soundfile as sf
    from f5_tts_mlx.generate import split_sentences, estimated_duration

    audio_np, sr = sf.read(ref_audio_path)
    if sr != 24000:
        raise ValueError(f"reference audio must be 24 kHz mono, got {sr} Hz")
    audio_np = audio_np.astype(np.float32)
    audio = mx.array(audio_np)[None]
    ref_samples = audio.shape[1]
    frames_per_sec = 24000 / 256

    # f5-tts-mlx 0.2.6 passes an mlx scalar as a dimension, which mlx 0.32 refuses: give the noise call plain ints
    normal = mx.random.normal
    mx.random.normal = lambda shape=(), *a, **kw: normal(tuple(int(d.item()) if isinstance(d, mx.array) else int(d) for d in shape), *a, **kw)
    try:
        return _generate(model, audio, audio_np, ref_text, text, ref_samples, frames_per_sec, steps, cfg_strength, sway_sampling_coef, target_rms, speed, seed)
    finally:
        mx.random.normal = normal


def _generate(model, audio, audio_np, ref_text, text, ref_samples, frames_per_sec, steps, cfg_strength, sway_sampling_coef, target_rms, speed=1.0, seed=None):
    from f5_tts_mlx.generate import split_sentences, estimated_duration
    pieces = []
    for sentence in split_sentences(text):
        dur = int(estimated_duration(mx.array(audio_np), ref_text, sentence, speed) * frames_per_sec)   # the pace follows the reference clip's, times speed
        wave, _ = model.sample(
            cond=audio,
            text=[ref_text + " " + sentence],   # raw chars — no pinyin conversion
            duration=dur,
            steps=steps,
            cfg_strength=cfg_strength,
            sway_sampling_coef=sway_sampling_coef,
            seed=seed,
        )
        wave = wave[ref_samples:]              # trim the reference prefix
        mx.eval(wave)
        pieces.append(np.array(wave).reshape(-1).astype(np.float32))
        mx.clear_cache()                       # MLX keeps freed buffers; over a few sentences that reached 10 GB on a 16 GB Mac

    out = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
    rms = float(np.sqrt(np.mean(out**2))) if len(out) else 0.0
    if rms > 1e-6:
        out = np.clip(out * (target_rms / rms), -1.0, 1.0)
    return out
