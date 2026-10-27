"""Somente instruções públicas revisadas; nunca cria ou envia transações."""
from pathlib import Path
import tomllib

from .config import ConfigError
from .rpc import validate_pubkey


def donation_instructions(path: str) -> dict:
    file = Path(path)
    if file.stat().st_size > 65536:
        raise ConfigError("Configuração de apoio muito grande.")
    with file.open("rb") as handle:
        config = tomllib.load(handle)
    allowed = {"enabled", "maintainer_verified", "project_label", "recipient", "accepted_mints"}
    if set(config) - allowed:
        raise ConfigError("Campos desconhecidos na configuração de apoio.")
    if config.get("enabled") is not True:
        return {"event": "donations_disabled", "enabled": False,
                "message": "Doações não configuradas. Não envie dinheiro usando apenas um nome de token/perfil."}
    if config.get("maintainer_verified") is not True:
        raise ConfigError("O mantenedor ainda não revisou o destinatário e os mints.")
    recipient = validate_pubkey(config.get("recipient"))
    mints = config.get("accepted_mints", [])
    if not isinstance(mints, list) or len(mints) > 20 or any(not isinstance(x, str) for x in mints):
        raise ConfigError("Lista de mints de apoio inválida.")
    if len(set(mints)) != len(mints):
        raise ConfigError("Mints de apoio duplicados.")
    for mint in mints:
        validate_pubkey(mint)
    label = config.get("project_label", "Pump Sentinel")
    if not isinstance(label, str) or not 1 <= len(label) <= 160 or any(ord(c) < 32 for c in label):
        raise ConfigError("Rótulo do projeto inválido.")
    return {"event": "voluntary_support_instructions", "enabled": True, "voluntary": True,
            "project_label": label, "network": "Solana mainnet-beta", "recipient": recipient,
            "accepted_assets": ["SOL"], "accepted_mints": mints,
            "executed_payment": False, "ownership_verified_by_bot": False,
            "warning": "Confira rede, destinatário e mint por canal confiável. A revisão do mantenedor não prova propriedade. Apoio não compra tokens, não promete retorno e não garante valorização. Nenhuma doação é exigida para usar o código."}
