from app import messages


def test_build_consent_keyboard_prefers_local_document(monkeypatch, tmp_path):
    document_path = tmp_path / "Документ.pdf"
    document_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(messages, "_CONSENT_DOCUMENT_PATH", document_path)

    keyboard = messages.build_consent_keyboard(
        policy_url="https://example.com/policy",
        rules_url="https://example.com/rules",
    )

    assert keyboard.inline_keyboard[0][0].callback_data == "consent_accept"
    assert keyboard.inline_keyboard[1][0].callback_data == "consent_doc:local"
    assert keyboard.inline_keyboard[1][0].url is None


def test_build_consent_keyboard_uses_links_when_local_document_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(messages, "_CONSENT_DOCUMENT_PATH", tmp_path / "missing.pdf")

    keyboard = messages.build_consent_keyboard(
        policy_url="https://example.com/policy",
        rules_url="https://example.com/rules",
    )

    assert keyboard.inline_keyboard[1][0].url == "https://example.com/policy"
    assert keyboard.inline_keyboard[2][0].url == "https://example.com/rules"
