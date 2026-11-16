from backend.cards.text import clean_card_text, leftover_shortcodes


def test_energy_icon_becomes_words() -> None:
    raw = (
        "As you play me, you may discard a card as an additional cost. "
        "If you do, reduce my cost by :rb_energy_2:."
    )

    assert clean_card_text(raw) == (
        "As you play me, you may discard a card as an additional cost. "
        "If you do, reduce my cost by 2 Energy."
    )


def test_keyword_brackets_are_stripped_and_might_icon_becomes_a_word() -> None:
    raw = "[Assault 2] (+2 :rb_might: while I'm an attacker.)"

    assert clean_card_text(raw) == "Assault 2 (+2 Might while I'm an attacker.)"


def test_adjacent_icons_are_separated_and_rune_icons_name_the_rune() -> None:
    raw = (
        "[Accelerate] (You may pay :rb_energy_1::rb_rune_fury: "
        "as an additional cost to have me enter ready.)"
    )

    assert clean_card_text(raw) == (
        "Accelerate (You may pay 1 Energy Fury Rune as an additional cost to have me enter ready.)"
    )


def test_no_text_marker_and_missing_text_clean_to_empty() -> None:
    assert clean_card_text("[NO TEXT]") == ""
    assert clean_card_text(None) == ""


def test_cost_arrow_symbols_become_readable_arrows() -> None:
    raw = (
        "[Action][>] Discard 1, :rb_energy_1::rb_rune_fury:: "
        "Banish me, then play me to your base, ignoring my cost."
    )

    assert clean_card_text(raw) == (
        "Action \u2192 Discard 1, 1 Energy Fury Rune: "
        "Banish me, then play me to your base, ignoring my cost."
    )


def test_double_arrow_symbol_is_kept_distinct_from_the_single_arrow() -> None:
    assert clean_card_text("[Level 6][>] [>>][Reaction][>] Draw 1.") == (
        "Level 6 \u2192 \u21d2 Reaction \u2192 Draw 1."
    )


def test_blank_lines_and_stray_spaces_are_dropped() -> None:
    raw = (
        "[Quick-Draw] (This has [Reaction]. When you play it, attach it to a unit you control.)\n"
        "[Equip] :rb_energy_1: (:rb_energy_1:: Attach this to a unit you control.)\n"
        " \n"
        "[Tank] (I must be assigned combat damage first.)"
    )

    assert clean_card_text(raw) == (
        "Quick-Draw (This has Reaction. When you play it, attach it to a unit you control.)\n"
        "Equip 1 Energy (1 Energy: Attach this to a unit you control.)\n"
        "Tank (I must be assigned combat damage first.)"
    )


def test_unknown_icon_shortcodes_stay_visible_so_they_can_be_reported() -> None:
    assert clean_card_text("Gain :rb_mystery: now.") == "Gain :rb_mystery: now."


def test_leftover_shortcodes_finds_what_cleaning_left_behind() -> None:
    cleaned = clean_card_text("Gain :rb_mystery: and :rb_energy_2:, then :rb_mystery: again.")

    assert leftover_shortcodes(cleaned) == [":rb_mystery:", ":rb_mystery:"]


def test_fully_cleaned_text_has_no_leftover_shortcodes() -> None:
    assert leftover_shortcodes(clean_card_text("[Assault 2] Pay :rb_energy_1:.")) == []


def test_exhaust_cost_becomes_a_word() -> None:
    raw = (
        ":rb_exhaust:: [Reaction] \u2014 [Add] :rb_rune_fury:. "
        "(Abilities that add resources can't be reacted to.)"
    )

    assert clean_card_text(raw) == (
        "Exhaust: Reaction \u2014 Add Fury Rune. "
        "(Abilities that add resources can't be reacted to.)"
    )
