from scripts.functionality_labels import canonicalize_functionality


def test_menu_synonyms_are_grouped_as_navigation_steps():
    variants = [
        "open owners dropdown menu",
        "open owners management dropdown",
        "open owners navigation menu",
        "toggle owners dropdown menu visibility",
    ]

    assert {
        canonicalize_functionality(label, "c2-navbar-owners")
        for label in variants
    } == {("Navegação", "Abrir menu de proprietários")}


def test_veterinarian_menu_is_not_a_final_veterinarian_feature():
    menu = canonicalize_functionality(
        "expand veterinarians navigation menu", "c5-navbar-vets"
    )
    add_vet = canonicalize_functionality(
        "initiate creation of a new veterinarian record",
        "c7-navbar-vets-add-new",
    )

    assert menu == ("Navegação", "Abrir menu de veterinários")
    assert add_vet == ("Veterinários", "Iniciar cadastro de veterinário")
    assert menu != add_vet


def test_owner_search_variants_group_but_stay_distinct_from_opening_menu():
    search_names = [
        "access owner directory",
        "access owners search functionality",
        "navigate to owner search page",
        "navigate to owners search page",
    ]

    assert {
        canonicalize_functionality(name, "c3-navbar-owners-search")
        for name in search_names
    } == {("Proprietários", "Acessar busca de proprietários")}
    assert canonicalize_functionality(
        "open owners dropdown menu", "c2-navbar-owners"
    ) != canonicalize_functionality(
        "access owners search functionality", "c3-navbar-owners-search"
    )


def test_owner_dropdown_display_is_not_mislabeled_as_menu_opening():
    assert canonicalize_functionality(
        "display the list of owners in the dropdown",
        "c2-navbar-owners",
    ) == ("Proprietários", "Exibir proprietários no menu")
    assert canonicalize_functionality(
        "display list of available owners",
        "c2-navbar-owners",
    ) == ("Proprietários", "Consultar proprietários disponíveis")


def test_pet_type_edit_is_distinct_from_listing_pet_types():
    assert canonicalize_functionality(
        "navigate to the edit form for a specific pet type",
        route="/petclinic/pettypes/5/edit",
    ) == ("Tipos de pets", "Editar tipo de pet")
    assert canonicalize_functionality(
        "view list of pet types", "c8-navbar-pet-types"
    ) == ("Tipos de pets", "Consultar tipos de pets")


def test_verification_descriptions_do_not_merge_with_user_goals():
    verification = canonicalize_functionality(
        "verify accessibility of the pet types management module",
        "c8-navbar-pet-types",
        "/petclinic/pettypes",
    )
    listing = canonicalize_functionality(
        "view list of pet types", "c8-navbar-pet-types"
    )

    assert verification == (
        "Validações",
        "Verificar acesso ao módulo de tipos de pets",
    )
    assert verification != listing
