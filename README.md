# Pump Sentinel

Bot pró-ativo de observação e defesa contra sinais de risco em tokens Solana, incluindo tokens que você verificar na Pump.fun. Código aberto sob licença MIT, com regras explicáveis e testes offline. **MVP 0.1.0, somente leitura, sem auditoria independente.**

O bot monitora automaticamente uma lista de mints, sinaliza autoridades mint/freeze, concentração em contas de token, extensões Token-2022, contas congeladas da carteira e reduções de saldo. Falhas de coleta, dados malformados e divergências entre slots geram um sinal conservador `PAUSE`. Não há promessa de identificar todo scam, evitar perdas, oferecer paridade de latência com bots de trading ou valorizar tokens.

## Começar sem conectar uma carteira

Requer Python 3.12 ou superior. Linux, macOS ou Windows com Python são suficientes para testar; nenhuma seed phrase é necessária.

```bash
python3 -m venv .venv
source .venv/bin/activate
# No Windows: .venv\Scripts\activate
pip install -e '.[dev]'
pump-sentinel demo
pump-sentinel support --config donations.example.toml
pytest -q
```

`demo` usa saldos completamente fictícios e não chama a rede. O mint mostrado na demonstração não implica que os dados sejam reais. `support` mostra que as doações estão desativadas por padrão.

## Monitoramento pró-ativo

```bash
cp config.example.toml config.toml
# Edite config.toml: mints = ["ENDERECO_MINT_VERIFICADO"]
# Opcional: wallet = "ENDERECO_PUBLICO_DA_SUA_CARTEIRA"
export SOLANA_RPC_URL='https://api.mainnet-beta.solana.com'
pump-sentinel once --config config.toml
pump-sentinel watch --config config.toml --cycles 2
# Quando estiver pronto para rodar continuamente em uma máquina online:
pump-sentinel watch --config config.toml
```

A lista pode conter até 20 mints. Por padrão, cada ciclo começa a cada 60 segundos; não há garantia de alerta instantâneo. Se a coleta demorar mais, o próximo ciclo só começa depois dela. São duas consultas por mint e uma terceira se houver carteira, com até duas retentativas por chamada. O RPC público pode limitar chamadas e não tem SLA oferecido pelo projeto. Chaves de RPC devem ficar na variável de ambiente, nunca no repositório. Arquivos `.env` não são carregados automaticamente.

O processo calcula os sinais sem você precisar consultar manualmente cada token. Alterações nos achados de risco ou no saldo produzem alertas JSON no terminal. Um heartbeat por ciclo mostra quantidade de mints, leituras incompletas, sinais de pausa e duração. O histórico fica em `data/sentinel.sqlite3`, com retenção padrão de 10.000 avaliações. A linha de base de saldo é separada por carteira e mint; leituras parciais não a atualizam. A variação é desde a última linha de base completa, não necessariamente desde o ciclo anterior.

**Ainda não há notificações para celular/Telegram, serviço hospedado 24/7 ou proteção automática de uma carteira real.** O processo precisa continuar rodando em uma máquina online. Este pacote não implanta um servidor nem contrata APIs. Não foi ativado contra um token específico sem os endereços fornecidos pelo proprietário.

## Sinais e controles

`PAUSE` recomenda suspender novas ações até revisão. `CAUTION` exige cautela. `OBSERVE` significa apenas que as regras implementadas não encontraram um achado naquele snapshot — não significa "seguro". `pause_new_actions` é um sinal para integrações, não uma trava sobre sua carteira. Nenhum desses campos permite compra/venda automática nesta versão.

A pontuação de 0 a 100 soma pesos heurísticos: WARNING=10, HIGH=25 e CRITICAL=50, limitada a 100. Não é probabilidade de scam. Limites padrão: maior conta acima de 20% e dez maiores acima de 60% do supply; esses parâmetros não são calibrados estatisticamente e podem ser ajustados no TOML. Reservas de protocolo frequentemente exigem revisão manual. Uma autoridade ou extensão pode ter uso legítimo; não é prova de fraude.

`getTokenLargestAccounts` retorna até 20 contas de token, não proprietários beneficiários. `excluded_accounts` aceita somente contas de token que você verificou como reserva/custódia. O bot preserva a concentração bruta e calcula a concentração observada restante sobre o **supply total**, sem renormalizar. Toda exclusão gera cautela. Mesmo assim, a amostra não cobre todas as contas nem revela controle comum entre elas.

Os saldos são tratados como quantidades inteiras e strings decimais, inclusive acima de 2^53. Não há preço, PnL, avaliação de liquidez, detector completo de rug pull, simulação de venda, classificação de pessoas, atribuição a IA ou recuperação de fundos. Uma redução de saldo pode ser sua própria transferência/venda. Uma falha do RPC não é um scam.

```bash
# Interromper o monitor antes da próxima consulta ou durante a espera:
touch PAUSE
# Permitir uma nova execução depois de revisar o problema:
rm PAUSE
# Analisar um snapshot local, cuja autenticidade não é verificada:
pump-sentinel analyze snapshot.json
```

`once` e `analyze` retornam código 2 quando há sinal de pausa/erro; `demo` retorna 0 por ser demonstração. `watch` encerrado pelo kill switch retorna 2; interrompido com Ctrl+C retorna 130. O kill switch não desfaz uma chamada já em andamento e não bloqueia ações de outros aplicativos.

## Apoio voluntário em SOL ou tokens

Quem se beneficiar pode apoiar voluntariamente o mantenedor. Não é obrigatório doar, comprar ou segurar um token para usar o código ou sugerir melhorias. Apoio não é investimento, pagamento exigido por uma suposta dívida, promessa de rendimento ou garantia de valorização.

Os nomes `azul777`, `suhail777` e `Suhail777` **não identificam um destinatário ou mint de maneira segura**. Até o mantenedor informar os endereços públicos e revisá-los, **não há endereço de doação divulgado por este pacote**.

```bash
cp donations.example.toml donations.toml
# Preencha recipient com carteira pública; accepted_mints com mints verificados.
# Somente após revisão humana: maintainer_verified = true e enabled = true.
pump-sentinel support --config donations.toml
```

Esse comando só mostra instruções. Não abre uma carteira, constrói transação, cobra ou transfere dinheiro. Antes de divulgar um arquivo público de doações, confirme o destinatário por outro canal confiável. O bot valida o formato do endereço, não quem controla a carteira. Veja [DONATIONS.md](DONATIONS.md).

## Código aberto e melhoria contínua

Contribuições, issues e forks são bem-vindos. Os testes rodam automaticamente em push e pull request pelo workflow incluído. Veja [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) e [a licença MIT](LICENSE).

A eficácia deve ser medida por cobertura, disponibilidade, incidentes documentados, alertas revisados como úteis e falsos positivos — não pelo preço ou volume de um token. Contagem de testes e doações também não provam eficácia no mundo real. O projeto não produz volume artificial, compras coordenadas, spam ou ataques a outros bots.

As fontes e limitações de dados estão em [docs/fontes.md](docs/fontes.md). A PumpPortal é independente da Pump.fun; seu streaming de trades é cobrado e **não está integrado nem ativado** nesta versão.
