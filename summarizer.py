#!/usr/bin/env python3
"""
Git Commits Summarizer
Lê todos os commits de um usuário específico em múltiplos projetos git
dentro de um intervalo de datas e gera um resumo em linguagem simples.

Provedores suportados: claude, gemini, ollama
"""

import json
import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Coleta de dados git
# ---------------------------------------------------------------------------


def find_git_repos(base_folder: str) -> list[Path]:
    """Encontra todos os repositórios git na pasta informada."""
    base = Path(base_folder).resolve()
    repos = []

    if (base / ".git").exists():
        repos.append(base)

    try:
        for item in sorted(base.iterdir()):
            if item.is_dir() and (item / ".git").exists():
                repos.append(item)
    except PermissionError as e:
        print(f"  Aviso: sem permissão para acessar {base}: {e}", file=sys.stderr)

    return repos


def get_commits(
    repo_path: Path, author: str, since: str, until_exclusive: str
) -> list[dict]:
    """Retorna todos os commits do autor no período informado."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--author={author}",
                f"--after={since}",
                f"--before={until_exclusive}",
                "--pretty=format:%H|||%s|||%ad|||%b<END_BODY>",
                "--date=short",
                "--no-merges",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return []

        commits = []
        for entry in result.stdout.split("<END_BODY>\n"):
            entry = entry.strip()
            if not entry or "|||" not in entry:
                continue
            parts = entry.split("|||", 3)
            if len(parts) < 3:
                continue
            commit_hash = parts[0].strip()
            subject = parts[1].strip()
            date = parts[2].strip()
            body = parts[3].strip() if len(parts) > 3 else ""
            body = body.replace("<END_BODY>", "").strip()

            if commit_hash:
                commits.append(
                    {
                        "hash": commit_hash,
                        "subject": subject,
                        "date": date,
                        "body": body,
                    }
                )

        return commits

    except subprocess.TimeoutExpired:
        print(f"  Aviso: timeout ao ler {repo_path.name}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  Aviso: erro ao ler {repo_path.name}: {e}", file=sys.stderr)
        return []


def get_commit_stats(repo_path: Path, commit_hash: str) -> str:
    """Retorna o resumo de arquivos alterados em um commit."""
    try:
        result = subprocess.run(
            ["git", "show", "--stat", "--format=", commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > 16:
                summary_line = lines[-1]
                lines = lines[:15] + [
                    f"  ... e mais {len(lines) - 16} arquivo(s)",
                    summary_line,
                ]
            return "\n".join(lines)
    except (subprocess.TimeoutExpired, Exception):
        pass
    return ""


def collect_all_changes(base_folder: str, author: str, since: str, until: str) -> dict:
    """Coleta todos os commits e alterações de todos os repositórios."""
    until_dt = datetime.strptime(until, "%Y-%m-%d") + timedelta(days=1)
    until_exclusive = until_dt.strftime("%Y-%m-%d")

    repos = find_git_repos(base_folder)
    if not repos:
        print(f"Nenhum repositório git encontrado em: {base_folder}", file=sys.stderr)
        return {}

    print(f"Encontrado(s) {len(repos)} repositório(s) git")

    all_data = {}
    for repo in repos:
        repo_name = repo.name
        print(f"  Escaneando: {repo_name} ...", end=" ")
        commits = get_commits(repo, author, since, until_exclusive)

        if not commits:
            print("(sem commits no período)")
            continue

        print(f"{len(commits)} commit(s) encontrado(s)")
        commits_with_stats = []
        for commit in commits:
            stats = get_commit_stats(repo, commit["hash"])
            commits_with_stats.append({**commit, "stats": stats})

        all_data[repo_name] = commits_with_stats

    return all_data


# ---------------------------------------------------------------------------
# Formatação dos dados para o prompt
# ---------------------------------------------------------------------------


def build_prompt(data: dict, author: str, since: str, until: str) -> tuple[str, str]:
    """Retorna (system_prompt, user_message) com os dados dos commits."""
    lines = []
    lines.append(f"Autor: {author}")
    lines.append(f"Período: {since} até {until}")
    lines.append("")

    total_commits = sum(len(c) for c in data.values())
    lines.append(f"Total: {total_commits} commit(s) em {len(data)} projeto(s)")
    lines.append("")

    for repo_name, commits in data.items():
        lines.append(f"=== PROJETO: {repo_name} ({len(commits)} commit(s)) ===")
        for commit in commits:
            lines.append(f"\n  Data: {commit['date']}")
            lines.append(f"  Mensagem: {commit['subject']}")
            if commit.get("body"):
                body_preview = commit["body"][:300]
                if len(commit["body"]) > 300:
                    body_preview += "..."
                lines.append(f"  Descrição: {body_preview}")
            if commit.get("stats"):
                lines.append(
                    "  Arquivos alterados:\n    "
                    + commit["stats"].replace("\n", "\n    ")
                )
        lines.append("")

    formatted_data = "\n".join(lines)

    system_prompt = (
        "Você gera relatórios de atividade técnica para gestores.\n\n"
        "Regras:\n"
        "- Português brasileiro, direto ao ponto\n"
        "- Sem emojis\n"
        "- Sem linguagem de marketing ou elogios às mudanças\n"
        "- Agrupe por projeto; dentro de cada projeto, liste as alterações em bullets curtos\n"
        "- Cada bullet descreve o que foi feito em uma linha, no passado (ex: 'Adicionado campo X', 'Corrigido erro em Y')\n"
        "- Evite repetir o nome do projeto dentro dos bullets\n"
        "- Ao final, uma linha com o total de projetos e alterações"
    )

    user_message = (
        f"Gere o relatório de atividades do período {since} a {until} "
        f"com base nos dados abaixo.\n\n"
        f"{formatted_data}"
    )

    return system_prompt, user_message


# ---------------------------------------------------------------------------
# Provedores de LLM
# ---------------------------------------------------------------------------


def run_claude(system_prompt: str, user_message: str, model: str) -> str:
    """Gera o resumo usando a API da Anthropic (Claude)."""
    try:
        import anthropic
    except ImportError:
        print(
            "Erro: pacote 'anthropic' não instalado. Execute: pip install anthropic",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Erro: defina a variável ANTHROPIC_API_KEY com sua chave da Anthropic.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            parts = []
            for text in stream.text_stream:
                print(text, end="", flush=True)
                parts.append(text)
        return "".join(parts)
    except anthropic.AuthenticationError:
        print("\nErro: ANTHROPIC_API_KEY inválida.", file=sys.stderr)
        sys.exit(1)
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e) or "too low" in str(e):
            print("\nErro: saldo insuficiente na Anthropic.", file=sys.stderr)
            print(
                "Adicione créditos em: https://console.anthropic.com/settings/billing",
                file=sys.stderr,
            )
        else:
            print(f"\nErro na requisição: {e}", file=sys.stderr)
        sys.exit(1)
    except anthropic.RateLimitError:
        print(
            "\nErro: limite de requisições atingido. Tente novamente em instantes.",
            file=sys.stderr,
        )
        sys.exit(1)
    except anthropic.APIConnectionError:
        print("\nErro: sem conexão com a API. Verifique sua internet.", file=sys.stderr)
        sys.exit(1)


def run_gemini(system_prompt: str, user_message: str, model: str) -> str:
    """Gera o resumo usando a API do Google Gemini (tier gratuito disponível)."""
    try:
        import google.generativeai as genai
    except ImportError:
        print(
            "Erro: pacote 'google-generativeai' não instalado.\n"
            "Execute: pip install google-generativeai",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "Erro: defina a variável GOOGLE_API_KEY com sua chave do Google AI Studio.\n"
            "Obtenha gratuitamente em: https://aistudio.google.com/app/apikey",
            file=sys.stderr,
        )
        sys.exit(1)

    genai.configure(api_key=api_key)
    gemini = genai.GenerativeModel(model, system_instruction=system_prompt)

    try:
        parts = []
        for chunk in gemini.generate_content(user_message, stream=True):
            text = chunk.text if hasattr(chunk, "text") and chunk.text else ""
            if text:
                print(text, end="", flush=True)
                parts.append(text)
        return "".join(parts)
    except Exception as e:
        print(f"\nErro ao chamar Gemini: {e}", file=sys.stderr)
        sys.exit(1)


def run_ollama(system_prompt: str, user_message: str, model: str, host: str) -> str:
    """Gera o resumo via API Ollama (funciona com servidores locais ou remotos na cloud)."""
    try:
        import requests
    except ImportError:
        print(
            "Erro: pacote 'requests' não instalado. Execute: pip install requests",
            file=sys.stderr,
        )
        sys.exit(1)

    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    try:
        response = requests.post(url, json=payload, stream=True, timeout=300)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(
            f"\nErro: não foi possível conectar ao servidor Ollama em {host}.\n"
            "Verifique se o endereço está correto e acessível.",
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(
                f"\nErro: modelo '{model}' não encontrado no servidor.\n"
                f"Verifique os modelos disponíveis no servidor Ollama.",
                file=sys.stderr,
            )
        else:
            print(f"\nErro HTTP do servidor Ollama: {e}", file=sys.stderr)
        sys.exit(1)

    parts = []
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        try:
            chunk = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        text = chunk.get("message", {}).get("content", "")
        if text:
            print(text, end="", flush=True)
            parts.append(text)
        if chunk.get("done"):
            break

    return "".join(parts)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def generate_summary(
    data: dict,
    author: str,
    since: str,
    until: str,
    llm: str,
    model: str,
    ollama_host: str = "http://localhost:11434",
) -> str:
    system_prompt, user_message = build_prompt(data, author, since, until)

    label = {"claude": "Claude", "gemini": "Gemini", "ollama": f"Ollama ({model})"}.get(
        llm, llm
    )
    print(f"\nGerando resumo com {label}...\n")
    print("=" * 60)

    if llm == "claude":
        summary = run_claude(system_prompt, user_message, model)
    elif llm == "gemini":
        summary = run_gemini(system_prompt, user_message, model)
    elif llm == "ollama":
        summary = run_ollama(system_prompt, user_message, model, ollama_host)
    else:
        print(f"Erro: provedor desconhecido '{llm}'", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

DEFAULT_MODELS = {
    "claude": "claude-opus-4-6",
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.2",
}


def main():
    parser = argparse.ArgumentParser(
        description="Resume commits git de um usuário em múltiplos projetos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Claude (requer ANTHROPIC_API_KEY)
  python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31

  # Gemini (gratuito — requer GOOGLE_API_KEY)
  python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --llm gemini

  # Ollama em servidor remoto/cloud
  python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --llm ollama --ollama-host https://meu-servidor.com

  # Ollama local
  python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --llm ollama --model llama3.2

Variáveis de ambiente:
  ANTHROPIC_API_KEY   Chave Anthropic       (para --llm claude)
                      Obtenha em: https://console.anthropic.com/settings/api-keys
  GOOGLE_API_KEY      Chave Google AI       (para --llm gemini)
                      Obtenha grátis em: https://aistudio.google.com/app/apikey
        """,
    )

    parser.add_argument("folder", help="Pasta contendo os repositórios git")
    parser.add_argument(
        "--author", required=True, help="Nome ou e-mail do autor para filtrar"
    )
    parser.add_argument("--since", required=True, help="Data de início (AAAA-MM-DD)")
    parser.add_argument(
        "--until", required=True, help="Data de fim, inclusiva (AAAA-MM-DD)"
    )
    parser.add_argument(
        "--llm",
        choices=["claude", "gemini", "ollama"],
        default="claude",
        help="Provedor de IA (padrão: claude)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Modelo a usar. Padrões: "
            "claude=claude-opus-4-6, gemini=gemini-2.0-flash, ollama=llama3.2"
        ),
    )
    parser.add_argument(
        "--ollama-host",
        default="http://localhost:11434",
        help="URL do servidor Ollama — local ou remoto/cloud (padrão: http://localhost:11434)",
    )
    parser.add_argument("--output", help="Arquivo para salvar o resumo (opcional)")

    args = parser.parse_args()

    try:
        datetime.strptime(args.since, "%Y-%m-%d")
        datetime.strptime(args.until, "%Y-%m-%d")
    except ValueError:
        print("Erro: datas devem estar no formato AAAA-MM-DD", file=sys.stderr)
        sys.exit(1)

    if args.since > args.until:
        print("Erro: --since não pode ser posterior a --until", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(args.folder):
        print(f"Erro: pasta não encontrada: {args.folder}", file=sys.stderr)
        sys.exit(1)

    model = args.model or DEFAULT_MODELS[args.llm]

    print(f"\nEscaneando repositórios em: {args.folder}")
    print(f"Autor: {args.author}")
    print(f"Período: {args.since} até {args.until}")
    print(f"Provedor: {args.llm} ({model})\n")

    data = collect_all_changes(args.folder, args.author, args.since, args.until)

    if not data:
        print(
            f"\nNenhum commit encontrado para '{args.author}' entre {args.since} e {args.until}."
        )
        sys.exit(0)

    total = sum(len(c) for c in data.values())
    print(f"\nTotal coletado: {total} commit(s) de {len(data)} projeto(s)")

    summary = generate_summary(
        data, args.author, args.since, args.until, args.llm, model, args.ollama_host
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("Relatório de Atividades\n")
            f.write(f"Autor: {args.author}\n")
            f.write(f"Período: {args.since} a {args.until}\n")
            f.write(f"Gerado por: {args.llm} ({model})\n")
            f.write("=" * 60 + "\n\n")
            f.write(summary)
        print(f"\nRelatório salvo em: {args.output}")


if __name__ == "__main__":
    main()
