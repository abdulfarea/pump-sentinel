# Contribuir com o Pump Sentinel

Este projeto é MIT. Uso, cópia e melhorias não exigem doação nem compra de token. Abra issues com dados reproduzíveis e pull requests pequenos. Não publique chaves, URLs RPC com credenciais, carteira pessoal configurada, mensagens privadas ou acusações contra pessoas.

## Desenvolvimento

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
ruff check src tests
pump-sentinel demo
```

Os testes devem ser offline e usar transportes mockados. Inclua cenários de dados parciais e inconsistentes para cada regra. Demonstre que a regra identifica uma característica técnica; não a apresente como prova automática de fraude. A pontuação atual não é probabilidade e não está calibrada com um conjunto de dados rotulado.

O monitor deve continuar sem chave privada, assinatura ou envio de transações. Uma futura camada de execução financeira precisa ser um projeto/integração separado, desativado por padrão, com revisão de segurança, simulação e autorização do proprietário. Não inclua manipulação de preço, volume artificial, compras forçadas, sandwich attacks, spam, perseguição ou exploração de sistemas alheios.

## Critério de melhoria

Uma melhoria deve aumentar cobertura ou qualidade de detecção sem esconder falhas de coleta. Exija dados verificáveis, casos de falso positivo e limites claros. Extensões Token-2022 novas não podem ser silenciosamente aprovadas. Os indicadores de concentração são entre contas de token, não entre pessoas.

Mudanças no endereço de doação exigem revisão destacada. Verifique com o mantenedor por um segundo canal antes de divulgar um novo destinatário. O campo `maintainer_verified` é somente uma declaração humana; não prova criptográfica de controle da carteira.

## Próximas integrações possíveis

Notificações privadas com fila de entrega e autenticação podem ser adicionadas quando houver destino autorizado. Decodificação de reservas Pump.fun/PumpSwap precisa de programa e layout verificados, sem tratar reserva virtual como liquidez real. Análise de transações deve separar observação on-chain de atribuição de identidade. Streaming comercial só deve ser integrado com opt-in e limite de custos, nunca com cobrança silenciosa.
