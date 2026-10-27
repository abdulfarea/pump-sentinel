# Versão 0.1.0 — 27/10/2026

Foi implementado um pacote Python com CLI, coletor Solana somente leitura, motor de risco explicável, observação automática de variação de saldo, auditoria local SQLite, deduplicação de alertas, heartbeat, kill switch, instruções separadas de doação voluntária e licença MIT.

A suíte local passou com **53 testes offline** e o lint Ruff sem erros. Ela inclui mocks HTTP, horários e cenários de dados parciais, além de dois ciclos de monitoramento simulado. A demonstração é fictícia. Esses resultados verificam comportamento do código nos cenários testados; não demonstram detecção de fraudes no mundo real ou segurança absoluta.

Não foram ativados monitoramento de um token específico, transferências, assinaturas, compras/vendas, doações, notificações privadas ou hospedagem 24/7. Não foi feito teste de eficácia contra scams reais nem auditoria de segurança independente.

Para configurar os alvos, o proprietário precisa fornecer cada endereço mint e, se desejar acompanhar a posição, sua carteira pública. Para doações, precisa fornecer uma carteira pública de recebimento e os mints aceitos. Nomes de perfil e símbolos não são suficientes. Não é necessário fornecer chave privada para nenhuma funcionalidade entregue.
