import re
import unicodedata


_NAVIGATION_LABELS = {
    "c1-navbar-home": ("Navegação", "Ir para a página inicial"),
    "c2-navbar-owners": ("Navegação", "Abrir menu de proprietários"),
    "c5-navbar-vets": ("Navegação", "Abrir menu de veterinários"),
}

_FUNCTION_LABELS = {
    "c3-navbar-owners-search": ("Proprietários", "Acessar busca de proprietários"),
    "c4-navbar-owners-add-new": ("Proprietários", "Iniciar cadastro de proprietário"),
    "c6-navbar-vets-all": ("Veterinários", "Consultar lista de veterinários"),
    "c7-navbar-vets-add-new": ("Veterinários", "Iniciar cadastro de veterinário"),
    "c8-navbar-pet-types": ("Tipos de pets", "Consultar tipos de pets"),
    "c9-navbar-specialties": ("Especialidades", "Consultar especialidades"),
}


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _category_from_route(route: str) -> str | None:
    path = _normalize(route)
    if "pettypes" in path or "pet type" in path:
        return "Tipos de pets"
    if "specialt" in path:
        return "Especialidades"
    if "vets" in path or "veterinarian" in path:
        return "Veterinários"
    if "owners" in path or "owner" in path:
        return "Proprietários"
    return None


def canonicalize_functionality(
    text: str,
    test_id: str | None = None,
    route: str = "",
) -> tuple[str, str]:
    """Return a display category and canonical label without changing source text."""
    normalized = _normalize(text)
    words = set(re.findall(r"[a-z0-9]+", normalized))

    if "display" in words and ("owner" in words or "owners" in words):
        if "dropdown" in words or "menu" in words:
            return "Proprietários", "Exibir proprietários no menu"
        return "Proprietários", "Consultar proprietários disponíveis"

    if "verify" in words or "verification" in words:
        category = _category_from_route(route)
        if "search" in words:
            return "Validações", "Verificar acesso à busca de proprietários"
        if category == "Tipos de pets":
            return "Validações", "Verificar acesso ao módulo de tipos de pets"
        if "link" in words or "active" in words:
            return "Validações", "Verificar estado do link de navegação"
        return "Validações", "Verificar acesso ao módulo"

    if test_id in _NAVIGATION_LABELS:
        return _NAVIGATION_LABELS[test_id]
    if test_id in _FUNCTION_LABELS:
        return _FUNCTION_LABELS[test_id]

    category = _category_from_route(route)

    if "owner" in words or "owners" in words:
        if words & {"search", "directory", "access", "accessible"}:
            return "Proprietários", "Acessar busca de proprietários"
        if words & {"create", "creation", "add", "new", "form", "workflow"}:
            return "Proprietários", "Iniciar cadastro de proprietário"
        if words & {"open", "expand", "toggle", "menu", "dropdown", "visibility"}:
            return "Navegação", "Abrir menu de proprietários"
        if words & {"display", "list", "available"}:
            return "Proprietários", "Consultar proprietários disponíveis"

    if "veterinarian" in words or "veterinarians" in words or "vet" in words:
        if words & {"open", "expand", "trigger", "menu", "dropdown", "navigation"}:
            return "Navegação", "Abrir menu de veterinários"
        if words & {"create", "creation", "add", "new", "form", "workflow"}:
            return "Veterinários", "Iniciar cadastro de veterinário"
        if words & {"edit", "editing", "modification", "modify", "inline"}:
            return "Veterinários", "Editar veterinário"
        if words & {"view", "list", "all"}:
            return "Veterinários", "Consultar lista de veterinários"

    if "pet" in words and ("type" in words or "types" in words):
        if words & {"edit", "editing", "modification", "modify"}:
            return "Tipos de pets", "Editar tipo de pet"
        return "Tipos de pets", "Consultar tipos de pets"

    if "specialty" in words or "specialties" in words:
        return "Especialidades", "Consultar especialidades"

    if "home" in words or "homepage" in words:
        return "Navegação", "Ir para a página inicial"

    if "edit" in words or "editing" in words or "modification" in words:
        if category:
            edit_names = {
                "Proprietários": "Editar proprietário",
                "Veterinários": "Editar veterinário",
                "Tipos de pets": "Editar tipo de pet",
                "Especialidades": "Editar especialidade",
            }
            return category, edit_names.get(category, "Abrir formulário de edição")
        return "Navegação", "Abrir formulário de edição"

    if "navigation" in words or "link" in words or "menu" in words:
        return "Navegação", "Verificar navegação"

    cleaned = normalized.strip(" .")
    return "Outras", cleaned[:1].upper() + cleaned[1:]
