from handlers.messages import _is_question


def test_is_question_recognizes_russian_questions():
    """Проверяем базовое распознавание вопросов на русском."""
    assert _is_question("Что нам задали по матану?") is True
    assert _is_question("Кто знает когда пара?") is True
    assert _is_question("Зачем нам это учить?") is True


def test_is_question_recognizes_slovak_questions():
    """Проверяем распознавание словацких вопросов."""
    assert _is_question("Kedy máme skúšku?") is True
    assert _is_question("Kto vie odpoveď?") is True
    assert _is_question("Ako sa to píše?") is True


def test_is_question_rejects_statements():
    """Проверяем, что утверждения не помечаются как вопросы."""
    assert _is_question("Спасибо, я всё понял.") is False
    assert _is_question("Я пойду на пару.") is False
    assert _is_question("Лектор задерживается.") is False


def test_is_question_accepts_keywords_without_question_mark():
    """Слова вроде 'кто знает' должны восприниматься как вопросы даже без '?'"""
    assert _is_question("кто-нибудь знает где мы вообще") is True
    assert _is_question("подскажите пожалуйста") is True
