"""Catálogo de permisos módulo:acción y matriz por defecto de los roles de sistema."""

MODULES = [
    "dashboard", "assets", "imports", "vulnerabilities", "kev", "tickets", "alerts",
    "workflow", "reports", "ai", "settings", "users", "roles", "audit",
]  # fmt: skip
ACTIONS = ["view", "create", "edit", "delete", "export"]
LETTER = {"V": "view", "C": "create", "E": "edit", "D": "delete", "X": "export"}

ADMIN = "Administrador"
ANALYST = "Analista de vulnerabilidades"
AUDITOR = "Auditor"
MANAGER = "Gerencia"

# Matriz del plan (sección 5). Las letras son V/C/E/D/X.
DEFAULT_MATRIX: dict[str, dict[str, str]] = {
    ADMIN: {
        "dashboard": "V", "assets": "VCEDX", "imports": "VC", "vulnerabilities": "VEX",
        "kev": "VX", "tickets": "VCEDX", "alerts": "V", "workflow": "VC", "reports": "VX",
        "ai": "V", "settings": "VE", "users": "VCED", "roles": "VCED", "audit": "VX",
    },
    ANALYST: {
        "dashboard": "V", "assets": "VCEX", "imports": "VC", "vulnerabilities": "VEX",
        "kev": "VX", "tickets": "VEX", "alerts": "V", "workflow": "VC", "reports": "VX",
        "ai": "V", "settings": "V",
    },
    AUDITOR: {
        "dashboard": "V", "assets": "V", "imports": "V", "vulnerabilities": "V", "kev": "V",
        "tickets": "V", "alerts": "V", "workflow": "V", "reports": "VX", "settings": "V",
        "users": "V", "roles": "V", "audit": "VX",
    },
    MANAGER: {
        "dashboard": "V", "kev": "V", "tickets": "V", "alerts": "V", "workflow": "V",
        "reports": "VX", "ai": "V",
    },
}  # fmt: skip

ROLE_DESCRIPTIONS = {
    ADMIN: "Acceso total, gestión de usuarios, roles y configuración",
    ANALYST: "Gestiona activos, importaciones, vulnerabilidades y tickets",
    AUDITOR: "Solo lectura de todo el sistema, más bitácora",
    MANAGER: "Dashboard, reportes y seguimiento de alto nivel",
}


def permission_codes(module_letters: dict[str, str]) -> set[str]:
    return {f"{m}:{LETTER[ch]}" for m, letters in module_letters.items() for ch in letters}


def all_permission_codes() -> set[str]:
    return {f"{m}:{a}" for m in MODULES for a in ACTIONS}
