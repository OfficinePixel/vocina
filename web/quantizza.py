"""Modello tiny-voca in int8 dinamico per il web (solo i MatMul; convoluzioni e costanti restano fp32).

    python quantizza.py MODELLO.onnx USCITA.onnx      (serve onnxruntime)

Misurato sul pilota il 2026-11-18: 21,4 → 8,5 MB, Whisper 12/12 come l'originale, all'ascolto indistinguibile
(giudizio dell'utente), più veloce in onnxruntime-web (38 contro ~30 volte il tempo reale in Firefox).
"""

import sys
from pathlib import Path

from onnxruntime.quantization import QuantType, quantize_dynamic


def quantizza(src: Path, dst: Path) -> None:
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul"])


if __name__ == "__main__":
    quantizza(Path(sys.argv[1]), Path(sys.argv[2]))
    print(sys.argv[2], f"{Path(sys.argv[2]).stat().st_size / 1e6:.1f} MB")
