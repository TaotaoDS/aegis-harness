"""Tests for PII sanitization middleware."""

from core_orchestrator.pii_sanitizer import (
    sanitize_email,
    sanitize_phone,
    sanitize_id_card,
    sanitize_credit_card,
    compose,
    default_pipeline,
)


# --- Email ---

class TestSanitizeEmail:
    def test_simple_email(self):
        assert sanitize_email("contact user@example.com now") == "contact [EMAIL_REDACTED] now"

    def test_multiple_emails(self):
        text = "a@b.com and c@d.org"
        result = sanitize_email(text)
        assert result == "[EMAIL_REDACTED] and [EMAIL_REDACTED]"

    def test_email_with_plus_and_dots(self):
        assert "[EMAIL_REDACTED]" in sanitize_email("mail a.b+tag@sub.domain.co.uk end")

    def test_no_false_positive_on_at_sign(self):
        assert sanitize_email("price is 5@unit") == "price is 5@unit"

    def test_empty_string(self):
        assert sanitize_email("") == ""


# --- Phone ---

class TestSanitizePhone:
    def test_chinese_mobile(self):
        assert sanitize_phone("call 13812345678") == "call [PHONE_REDACTED]"

    def test_us_formatted_with_dashes(self):
        assert sanitize_phone("call 555-123-4567") == "call [PHONE_REDACTED]"

    def test_us_formatted_with_parens(self):
        assert sanitize_phone("call (555) 123-4567") == "call [PHONE_REDACTED]"

    def test_international_plus(self):
        assert "[PHONE_REDACTED]" in sanitize_phone("call +86 138 1234 5678")

    def test_no_false_positive_short_number(self):
        assert sanitize_phone("room 12345") == "room 12345"

    def test_embedded_in_chinese_text(self):
        result = sanitize_phone("请拨打13912345678联系我")
        assert "13912345678" not in result
        assert "[PHONE_REDACTED]" in result


# --- ID Card ---

class TestSanitizeIdCard:
    def test_standard_18_digit(self):
        assert sanitize_id_card("ID: 110101199001011234") == "ID: [IDCARD_REDACTED]"

    def test_ending_with_uppercase_x(self):
        assert sanitize_id_card("ID: 11010119900101123X") == "ID: [IDCARD_REDACTED]"

    def test_ending_with_lowercase_x(self):
        assert sanitize_id_card("ID: 11010119900101123x") == "ID: [IDCARD_REDACTED]"

    def test_no_false_positive_17_digits(self):
        assert sanitize_id_card("num 12345678901234567 end") == "num 12345678901234567 end"

    def test_no_false_positive_19_digits(self):
        # 19 digits should not match as ID card
        text = "num 1234567890123456789 end"
        result = sanitize_id_card(text)
        assert "[IDCARD_REDACTED]" not in result


# --- Credit Card ---

class TestSanitizeCreditCard:
    def test_visa_16_digit(self):
        assert sanitize_credit_card("card 4111111111111111") == "card [CREDITCARD_REDACTED]"

    def test_with_spaces(self):
        assert sanitize_credit_card("card 4111 1111 1111 1111") == "card [CREDITCARD_REDACTED]"

    def test_with_dashes(self):
        assert sanitize_credit_card("card 4111-1111-1111-1111") == "card [CREDITCARD_REDACTED]"

    def test_amex_15_digit(self):
        result = sanitize_credit_card("card 371449635398431")
        assert "[CREDITCARD_REDACTED]" in result

    def test_no_false_positive_short(self):
        assert sanitize_credit_card("num 123456789012 end") == "num 123456789012 end"


# --- Compose ---

class TestCompose:
    def test_compose_single(self):
        upper = compose(str.upper)
        assert upper("hello") == "HELLO"

    def test_compose_ordering(self):
        add_a = lambda t: t + "A"
        add_b = lambda t: t + "B"
        pipeline = compose(add_a, add_b)
        assert pipeline("") == "AB"

    def test_compose_empty(self):
        identity = compose()
        assert identity("hello") == "hello"


# --- Default Pipeline ---

class TestDefaultPipeline:
    def test_mixed_pii(self):
        text = "email: user@test.com phone: 13800138000 id: 110101199001011234 card: 4111111111111111"
        result = default_pipeline()(text)
        assert "user@test.com" not in result
        assert "13800138000" not in result
        assert "110101199001011234" not in result
        assert "4111111111111111" not in result
        assert "[EMAIL_REDACTED]" in result
        assert "[PHONE_REDACTED]" in result
        assert "[IDCARD_REDACTED]" in result
        assert "[CREDITCARD_REDACTED]" in result

    def test_no_pii(self):
        text = "hello world, nothing sensitive here"
        assert default_pipeline()(text) == text

    def test_chinese_text_with_pii(self):
        text = "请联系张三，邮箱user@test.com，电话13800138000，身份证110101199001011234"
        result = default_pipeline()(text)
        assert "张三" in result
        assert "user@test.com" not in result
        assert "13800138000" not in result
        assert "110101199001011234" not in result

    def test_idempotent(self):
        text = "email: user@test.com phone: 13800138000"
        pipeline = default_pipeline()
        once = pipeline(text)
        twice = pipeline(once)
        assert once == twice


# --- Composability ---

class TestComposability:
    def test_custom_sanitizer_in_pipeline(self):
        custom = lambda t: t.replace("SECRET", "[CUSTOM_REDACTED]")
        pipeline = compose(default_pipeline(), custom)
        result = pipeline("SECRET and user@test.com")
        assert "[CUSTOM_REDACTED]" in result
        assert "[EMAIL_REDACTED]" in result

    def test_pipeline_is_callable(self):
        assert callable(default_pipeline())
