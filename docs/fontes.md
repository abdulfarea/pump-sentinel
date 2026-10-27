# Fontes técnicas verificadas em 27/10/2026

O Pump Sentinel usa apenas métodos de leitura da Solana nesta versão. A PumpPortal é um provedor de terceiros, não uma API oficial da Pump.fun. Sua documentação informa que `subscribeTokenTrade` e `subscribeAccountTrade` exigem chave e carteira financiada com pelo menos 0,02 SOL, com cobrança de 0,01 SOL por 10.000 eventos. Por isso não incluímos nem ativamos esse streaming no MVP. As condições podem mudar. [1] [2]

`getTokenLargestAccounts` retorna até 20 **contas de token**, não os maiores proprietários econômicos. Uma conta pode ser uma reserva de protocolo; um proprietário pode controlar várias contas. O indicador calculado pelo bot não representa distribuição completa entre pessoas. [3]

`getAccountInfo` permite ler o estado de uma conta. A implementação exige dados `jsonParsed` reconhecidos e não aceita uma resposta incompleta como ausência de autoridade. [4]

`getTokenAccountsByOwner` permite consultar as contas de um mint pertencentes à carteira informada. O bot soma quantidades inteiras, sem estimar preço ou lucro. [5]

Extensões Token-2022 podem impor taxas, hooks de transferência, delegados permanentes, não transferibilidade, estados padrão e pausas. A presença de uma extensão é uma característica técnica, não prova de fraude. Extensões desconhecidas ou não suportadas exigem revisão. [6]

Dados no compromisso `confirmed` reduzem atraso em relação a `finalized`, mas ainda podem sofrer reorganização. Leituras feitas em chamadas separadas não constituem um snapshot atômico. O bot verifica a diferença de slots e falha de maneira conservadora quando os dados ficam incompletos ou inconsistentes. Não promete antecipação de transações, proteção de preço nem paridade de latência.

## References

[1]: https://pumpportal.fun/data-api/real-time/ "PumpPortal: dados em tempo real e cobrança"
[2]: https://pumpportal.fun/ "PumpPortal: provedor de terceiros"
[3]: https://solana.com/docs/rpc/http/gettokenlargestaccounts "Solana: getTokenLargestAccounts"
[4]: https://solana.com/docs/rpc/http/getaccountinfo "Solana: getAccountInfo"
[5]: https://solana.com/docs/rpc/http/gettokenaccountsbyowner "Solana: getTokenAccountsByOwner"
[6]: https://solana.com/docs/tokens/extensions "Solana: extensões Token-2022"
