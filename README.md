# git-commits-summarizer

Ferramenta de linha de comando que lê commits de um autor em múltiplos repositórios git e gera um relatório de atividades em linguagem simples usando IA.

## Provedores suportados

| Provedor | Modelo padrão | Custo |
|----------|--------------|-------|
| Claude (Anthropic) | `claude-opus-4-6` | Pago |
| Gemini (Google) | `gemini-2.0-flash` | Gratuito |
| Ollama | `llama3.2` | Gratuito (local ou remoto) |

## Instalação

```bash
pip install -r requirements.txt
```

> Instale apenas os pacotes do(s) provedor(es) que for usar.

## Configuração

Copie o arquivo de exemplo e preencha as chaves necessárias:

```bash
cp .env.example .env
```

| Variável | Provedor | Onde obter |
|----------|----------|-----------|
| `ANTHROPIC_API_KEY` | Claude | https://console.anthropic.com/settings/api-keys |
| `GOOGLE_API_KEY` | Gemini | https://aistudio.google.com/app/apikey |

Para Ollama não é necessária chave de API.

## Uso

```bash
python summarizer.py <pasta> --author "<nome>" --since <AAAA-MM-DD> --until <AAAA-MM-DD> [opções]
```

### Argumentos

| Argumento | Descrição |
|-----------|-----------|
| `folder` | Pasta contendo os repositórios git |
| `--author` | Nome ou e-mail do autor para filtrar |
| `--since` | Data de início no formato `AAAA-MM-DD` |
| `--until` | Data de fim no formato `AAAA-MM-DD` (inclusiva) |
| `--llm` | Provedor de IA: `claude`, `gemini` ou `ollama` (padrão: `claude`) |
| `--model` | Modelo a usar (opcional, usa o padrão do provedor) |
| `--ollama-host` | URL do servidor Ollama (padrão: `http://localhost:11434`) |
| `--output` | Arquivo para salvar o relatório (opcional) |

### Exemplos

```bash
# Claude
python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31

# Gemini (gratuito)
python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --llm gemini

# Ollama local
python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --llm ollama

# Ollama em servidor remoto
python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --llm ollama --ollama-host https://meu-servidor.com

# Salvar relatório em arquivo
python summarizer.py ~/projetos --author "João" --since 2024-01-01 --until 2024-01-31 --output relatorio.txt
```

## Como funciona

1. Varre recursivamente a pasta informada em busca de repositórios git
2. Coleta todos os commits do autor no período, incluindo estatísticas de arquivos alterados
3. Monta um prompt com os dados coletados e envia ao provedor de IA escolhido
4. O relatório é exibido em tempo real (streaming) e pode ser salvo em arquivo
