"""CLI: review a sales call transcript/recording like a code review.

Usage:
    python -m src.call_analysis.cli --transcript call.txt
    python -m src.call_analysis.cli --audio call.mp3 --whisper-model base
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from src.call_analysis.analyzer import generate_call_analysis
from src.call_analysis.pdf import render_call_analysis_pdf
from src.call_analysis.transcription import transcribe_audio


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisa uma call de vendas e aponta o 'bug' que mais custou o fechamento."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", help="Caminho para o arquivo de áudio da call")
    source.add_argument("--transcript", help="Caminho para uma transcrição já pronta (.txt)")

    parser.add_argument("--context", help="Arquivo .txt com contexto adicional (o que estava sendo vendido, etc.)")
    parser.add_argument("--whisper-model", default="base", help="Tamanho do modelo Whisper (tiny/base/small/medium/large)")
    parser.add_argument("--language", default="pt", help="Idioma do áudio/transcrição (código Whisper, ex: pt)")
    parser.add_argument("--output-dir", default="output", help="Diretório de saída do relatório")
    parser.add_argument("--model", default=None, help="Sobrescreve o modelo Claude usado")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    if args.transcript:
        if not os.path.exists(args.transcript):
            print(f"Transcrição não encontrada: {args.transcript}", file=sys.stderr)
            return 1
        with open(args.transcript, encoding="utf-8") as f:
            transcript = f.read()
    else:
        if not os.path.exists(args.audio):
            print(f"Áudio não encontrado: {args.audio}", file=sys.stderr)
            return 1
        print("Transcrevendo áudio com Whisper (pode demorar)...")
        try:
            transcript = transcribe_audio(
                args.audio, model_size=args.whisper_model, language=args.language
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    context = None
    if args.context:
        if not os.path.exists(args.context):
            print(f"Arquivo de contexto não encontrado: {args.context}", file=sys.stderr)
            return 1
        with open(args.context, encoding="utf-8") as f:
            context = f.read()

    kwargs = {}
    if args.model:
        kwargs["model"] = args.model

    print("Analisando a call com Claude...")
    analysis = generate_call_analysis(transcript, context=context, **kwargs)

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, "analise_call.pdf")
    render_call_analysis_pdf(analysis, output_path)

    print(f"\nNota: {analysis.overall_score}/10")
    print(f"Bug que mais custou a call: {analysis.critical_issue}")
    print(f"\nRelatório completo salvo em {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
